"""GitHub REST API (read-only). Token: env ``GITHUB_TOKEN`` or per-user secret ``github_pat``."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable
from urllib.parse import quote

import httpx

from app import db
from app import identity

__version__ = "1.0.0"
TOOL_ID = "github"
TOOL_DOMAIN = "github"
TOOL_LABEL = "GitHub"
TOOL_DESCRIPTION = (
    "Search code and issues, list PRs, read files via GitHub REST (token or user secret github_pat)."
)
TOOL_TRIGGERS = (
    "github",
    "repository",
    "repo",
    "pull request",
    "issue",
    "gist",
)

GITHUB_API = "https://api.github.com"
USER_SECRET_KEY = "github_pat"
HTTP_TIMEOUT = 30.0
MAX_SEARCH_ITEMS = 20
MAX_FILE_CHARS = 120_000


def _is_error_payload(status: int, data: Any) -> bool:
    if status == 0:
        return True
    return isinstance(data, dict) and data.get("ok") is False


def _parse_user_pat(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return s
    if isinstance(obj, dict):
        return str(obj.get("token") or obj.get("pat") or "").strip()
    return s


def _token() -> str | None:
    _tid, uid = identity.get_identity()
    raw = db.user_secret_get_plaintext(uid, USER_SECRET_KEY)
    if raw:
        t = _parse_user_pat(raw)
        if t:
            return t
    env_t = os.environ.get("GITHUB_TOKEN", "").strip()
    return env_t or None


def _headers(tok: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {tok}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "jetpack-agent-layer-github-tool",
    }


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    tok = _token()
    if not tok:
        return (
            0,
            {
                "ok": False,
                "error": (
                    "No GitHub token: set GITHUB_TOKEN in the agent environment (e.g. docker/.env) "
                    f"or register a user secret `{USER_SECRET_KEY}` via register_secrets "
                    '(JSON {"token":"ghp_…"} or github_pat_… string).'
                ),
            },
        )
    url = f"{GITHUB_API}{path}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.request(method, url, headers=_headers(tok), params=params)
    except httpx.HTTPError as e:
        return 0, {"ok": False, "error": f"http error: {e}"}
    try:
        data = r.json() if r.content else None
    except json.JSONDecodeError:
        data = {"raw": r.text[:2000]}
    if r.status_code >= 400:
        msg = None
        if isinstance(data, dict):
            msg = data.get("message")
        return r.status_code, {
            "ok": False,
            "status": r.status_code,
            "error": msg or r.reason_phrase or "request failed",
            "github": data if isinstance(data, dict) else str(data)[:500],
        }
    return r.status_code, data


def github_search_code(arguments: dict[str, Any]) -> str:
    q = (arguments.get("query") or "").strip()
    if not q:
        return json.dumps({"ok": False, "error": "query is required"})
    per_page = min(max(int(arguments.get("per_page") or 10), 1), MAX_SEARCH_ITEMS)
    status, data = _request(
        "GET",
        "/search/code",
        params={"q": q, "per_page": per_page},
    )
    if _is_error_payload(status, data):
        return json.dumps(data, ensure_ascii=False)
    items_out: list[dict[str, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        for it in data["items"][:per_page]:
            if not isinstance(it, dict):
                continue
            items_out.append(
                {
                    "name": it.get("name"),
                    "path": it.get("path"),
                    "html_url": it.get("html_url"),
                    "repository": (it.get("repository") or {}).get("full_name"),
                }
            )
    return json.dumps(
        {
            "ok": True,
            "total_count": data.get("total_count") if isinstance(data, dict) else None,
            "items": items_out,
        },
        ensure_ascii=False,
    )


def github_search_issues(arguments: dict[str, Any]) -> str:
    q = (arguments.get("query") or "").strip()
    if not q:
        return json.dumps({"ok": False, "error": "query is required"})
    per_page = min(max(int(arguments.get("per_page") or 10), 1), MAX_SEARCH_ITEMS)
    status, data = _request(
        "GET",
        "/search/issues",
        params={"q": q, "per_page": per_page},
    )
    if _is_error_payload(status, data):
        return json.dumps(data, ensure_ascii=False)
    items_out: list[dict[str, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        for it in data["items"][:per_page]:
            if not isinstance(it, dict):
                continue
            items_out.append(
                {
                    "number": it.get("number"),
                    "title": it.get("title"),
                    "state": it.get("state"),
                    "html_url": it.get("html_url"),
                    "repository_url": it.get("repository_url"),
                    "pull_request": bool(it.get("pull_request")),
                }
            )
    return json.dumps(
        {
            "ok": True,
            "total_count": data.get("total_count") if isinstance(data, dict) else None,
            "items": items_out,
        },
        ensure_ascii=False,
    )


def github_get_file(arguments: dict[str, Any]) -> str:
    owner = (arguments.get("owner") or "").strip()
    repo = (arguments.get("repo") or "").strip()
    path = (arguments.get("path") or "").strip().lstrip("/")
    ref = (arguments.get("ref") or "").strip() or None
    if not owner or not repo or not path:
        return json.dumps(
            {"ok": False, "error": "owner, repo, and path are required"},
        )
    enc_path = quote(path, safe="")
    p = f"/repos/{owner}/{repo}/contents/{enc_path}"
    params = {}
    if ref:
        params["ref"] = ref
    status, data = _request("GET", p, params=params or None)
    if _is_error_payload(status, data):
        return json.dumps(data, ensure_ascii=False)
    if not isinstance(data, dict):
        return json.dumps({"ok": False, "error": "unexpected response"})
    if data.get("type") != "file":
        return json.dumps(
            {
                "ok": False,
                "error": "not a file (directory or submodule); use GitHub UI or search_code",
                "type": data.get("type"),
            },
        )
    b64 = data.get("encoding") == "base64" and data.get("content")
    if not b64:
        return json.dumps(
            {
                "ok": False,
                "error": "no file content (too large or empty)",
                "sha": data.get("sha"),
            },
        )
    try:
        raw = base64.b64decode(
            "".join(str(b64).splitlines()),
            validate=False,
        ).decode("utf-8", errors="replace")
    except Exception as e:
        return json.dumps({"ok": False, "error": f"decode failed: {e}"})
    if len(raw) > MAX_FILE_CHARS:
        raw = raw[:MAX_FILE_CHARS] + "\n… (truncated)"
    return json.dumps(
        {
            "ok": True,
            "path": data.get("path"),
            "sha": data.get("sha"),
            "size": data.get("size"),
            "html_url": data.get("html_url"),
            "content": raw,
        },
        ensure_ascii=False,
    )


def github_list_pull_requests(arguments: dict[str, Any]) -> str:
    owner = (arguments.get("owner") or "").strip()
    repo = (arguments.get("repo") or "").strip()
    if not owner or not repo:
        return json.dumps({"ok": False, "error": "owner and repo are required"})
    state = (arguments.get("state") or "open").strip().lower()
    if state not in ("open", "closed", "all"):
        state = "open"
    per_page = min(max(int(arguments.get("per_page") or 10), 1), MAX_SEARCH_ITEMS)
    status, data = _request(
        "GET",
        f"/repos/{owner}/{repo}/pulls",
        params={"state": state, "per_page": per_page},
    )
    if _is_error_payload(status, data):
        return json.dumps(data, ensure_ascii=False)
    items_out: list[dict[str, Any]] = []
    if isinstance(data, list):
        for it in data[:per_page]:
            if not isinstance(it, dict):
                continue
            items_out.append(
                {
                    "number": it.get("number"),
                    "title": it.get("title"),
                    "state": it.get("state"),
                    "html_url": it.get("html_url"),
                    "draft": it.get("draft"),
                    "user": (it.get("user") or {}).get("login"),
                }
            )
    if not isinstance(data, list):
        return json.dumps(
            {"ok": False, "error": "unexpected response"}, ensure_ascii=False
        )
    return json.dumps({"ok": True, "items": items_out}, ensure_ascii=False)


def github_get_issue(arguments: dict[str, Any]) -> str:
    owner = (arguments.get("owner") or "").strip()
    repo = (arguments.get("repo") or "").strip()
    try:
        num = int(arguments.get("issue_number"))
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "issue_number must be an integer"})
    if not owner or not repo:
        return json.dumps({"ok": False, "error": "owner and repo are required"})
    status, data = _request("GET", f"/repos/{owner}/{repo}/issues/{num}")
    if _is_error_payload(status, data):
        return json.dumps(data, ensure_ascii=False)
    if not isinstance(data, dict):
        return json.dumps({"ok": False, "error": "unexpected response"})
    body = str(data.get("body") or "")
    if len(body) > 24_000:
        body = body[:24_000] + "\n… (truncated)"
    return json.dumps(
        {
            "ok": True,
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "html_url": data.get("html_url"),
            "user": (data.get("user") or {}).get("login"),
            "TOOL_LABELs": [
                x.get("name") for x in (data.get("TOOL_LABELs") or []) if isinstance(x, dict)
            ],
            "pull_request": bool(data.get("pull_request")),
            "body": body,
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "github_search_code": github_search_code,
    "github_search_issues": github_search_issues,
    "github_get_file": github_get_file,
    "github_list_pull_requests": github_list_pull_requests,
    "github_get_issue": github_get_issue,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "github_search_code",
            "TOOL_DESCRIPTION": (
                "Search code on GitHub (same query syntax as github.com search). "
                "Needs GITHUB_TOKEN (env) or user secret github_pat. Read-only PAT recommended."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "GitHub code search query, e.g. org:myorg filename:flake.nix",
                    },
                    "per_page": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max results 1–20 (default 10).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_search_issues",
            "TOOL_DESCRIPTION": (
                "Search issues and pull requests across GitHub. "
                "Query examples: repo:owner/name is:open TOOL_LABEL:bug"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "per_page": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max results 1–20 (default 10).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_get_file",
            "TOOL_DESCRIPTION": (
                "Fetch a single file from a repository (decoded UTF-8 text). "
                "Large files are truncated. Not for directories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "path": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "File path in repo, e.g. README.md",
                    },
                    "ref": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Optional branch, tag, or commit SHA",
                    },
                },
                "required": ["owner", "repo", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_list_pull_requests",
            "TOOL_DESCRIPTION": "List pull requests for a repository (open, closed, or all).",
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed", "all"],
                        "TOOL_DESCRIPTION": "Default open",
                    },
                    "per_page": {"type": "integer", "TOOL_DESCRIPTION": "1–20, default 10"},
                },
                "required": ["owner", "repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_get_issue",
            "TOOL_DESCRIPTION": (
                "Get one issue or pull request by number (body may be truncated). "
                "PRs are returned via the issues API when pull_request is present."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "issue_number": {"type": "integer"},
                },
                "required": ["owner", "repo", "issue_number"],
            },
        },
    },
]
