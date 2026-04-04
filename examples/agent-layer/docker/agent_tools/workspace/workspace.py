"""Local workspace files under ``AGENT_WORKSPACE_ROOT`` (host directory mounted in the container).

Separate from ``github_get_file`` (remote API). If ``AGENT_WORKSPACE_ROOT`` is unset or not a directory,
all tools return a clear ``ok: false`` hint to configure the mount.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app import config

__version__ = "1.0.0"
TOOL_ID = "workspace"
AGENT_TOOL_ROUTER_CATEGORY = "workspace"
AGENT_TOOL_ROUTER_TRIGGERS = (
    "workspace",
    "local file",
    "mounted directory",
    "agent_workspace",
)

MAX_FILE_BYTES = config.WORKSPACE_MAX_FILE_BYTES
MAX_LIST_ENTRIES = config.WORKSPACE_MAX_LIST_ENTRIES
MAX_GLOB_FILES = config.WORKSPACE_MAX_GLOB_FILES
MAX_SEARCH_FILES = config.WORKSPACE_MAX_SEARCH_FILES
MAX_SEARCH_MATCHES = config.WORKSPACE_MAX_SEARCH_MATCHES
MAX_LINE_READ = config.WORKSPACE_MAX_READ_LINES
SEARCH_MAX_FILE_BYTES = config.WORKSPACE_SEARCH_MAX_FILE_BYTES


def _disabled_message() -> str:
    return (
        "Local workspace tools are disabled: set AGENT_WORKSPACE_ROOT to an absolute path inside the "
        "container and mount the host directory there (see agent-layer docker compose / TOOLS.md). "
        "This is separate from github_get_file, which reads from the GitHub API, not from disk."
    )


def _real_root() -> str | None:
    raw = (config.WORKSPACE_ROOT or "").strip()
    if not raw:
        return None
    try:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            return None
        r = os.path.realpath(str(p))
    except OSError:
        return None
    if not os.path.isdir(r):
        return None
    return r


def _reject_rel(rel: str) -> str | None:
    s = (rel or "").strip()
    if "\x00" in s:
        return "path contains invalid character"
    if s.startswith("/"):
        return "path must be relative to workspace root (no leading /)"
    parts = Path(s).parts
    if ".." in parts:
        return "path must not contain .."
    return None


def _safe_resolve(rel: str) -> tuple[str | None, str | None]:
    err = _reject_rel(rel)
    if err:
        return None, err
    root = _real_root()
    if not root:
        return None, _disabled_message()
    joined = os.path.join(root, rel.replace("/", os.sep))
    try:
        real = os.path.realpath(joined)
    except OSError as e:
        return None, f"invalid path: {e}"
    if real == root:
        return real, None
    prefix = root + os.sep
    if not (real == root or real.startswith(prefix)):
        return None, "path resolves outside workspace root"
    return real, None


def _is_probably_text(data: bytes) -> bool:
    if not data:
        return True
    if b"\x00" in data[:8192]:
        return False
    return True


def workspace_stat(arguments: dict[str, Any]) -> str:
    rel = arguments.get("path") or ""
    path, err = _safe_resolve(str(rel))
    if err:
        return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
    if not os.path.lexists(path):
        return json.dumps(
            {"ok": False, "error": "path does not exist", "path": str(rel)},
            ensure_ascii=False,
        )
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    is_dir = False
    try:
        is_dir = Path(path).is_dir()
    except OSError:
        pass
    return json.dumps(
        {
            "ok": True,
            "path": str(rel),
            "is_dir": is_dir,
            "is_symlink": os.path.islink(path),
            "size": None if is_dir else st.st_size,
            "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )


def workspace_list_dir(arguments: dict[str, Any]) -> str:
    rel = arguments.get("path") or "."
    path, err = _safe_resolve(str(rel))
    if err:
        return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
    if not os.path.isdir(path):
        return json.dumps(
            {"ok": False, "error": "not a directory", "path": str(rel)},
            ensure_ascii=False,
        )
    try:
        want_files = bool(arguments.get("include_files", True))
        want_dirs = bool(arguments.get("include_directories", True))
    except Exception:
        want_files, want_dirs = True, True
    entries: list[dict[str, Any]] = []
    try:
        for name in sorted(os.listdir(path)):
            if name in (".", ".."):
                continue
            fp = os.path.join(path, name)
            try:
                is_dir = os.path.isdir(fp)
                is_link = os.path.islink(fp)
            except OSError:
                continue
            if is_dir and not want_dirs:
                continue
            if not is_dir and not want_files:
                continue
            rel_child = str(Path(str(rel)) / name) if str(rel) not in (".", "") else name
            entries.append(
                {
                    "name": name,
                    "path": rel_child.replace("\\", "/"),
                    "is_dir": is_dir,
                    "is_symlink": is_link,
                }
            )
            if len(entries) >= MAX_LIST_ENTRIES:
                break
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "path": str(rel).replace("\\", "/") or ".",
            "entries": entries,
            "truncated": len(entries) >= MAX_LIST_ENTRIES,
            "max_entries": MAX_LIST_ENTRIES,
        },
        ensure_ascii=False,
    )


def workspace_read_file(arguments: dict[str, Any]) -> str:
    rel = arguments.get("path") or ""
    path, err = _safe_resolve(str(rel))
    if err:
        return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
    if not os.path.isfile(path):
        return json.dumps(
            {"ok": False, "error": "not a regular file", "path": str(rel)},
            ensure_ascii=False,
        )
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    if size > MAX_FILE_BYTES:
        return json.dumps(
            {
                "ok": False,
                "error": f"file too large (>{MAX_FILE_BYTES} bytes); increase AGENT_WORKSPACE_MAX_FILE_BYTES",
                "size": size,
            },
            ensure_ascii=False,
        )
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    if not _is_probably_text(raw):
        return json.dumps(
            {"ok": False, "error": "file looks binary; not returned as text", "path": str(rel)},
            ensure_ascii=False,
        )
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    start = int(arguments.get("start_line") or 1)
    limit = arguments.get("limit_lines")
    try:
        start = max(1, start)
        if limit is None:
            chunk = lines
        else:
            lim = max(0, int(limit))
            chunk = lines[start - 1 : start - 1 + lim]
    except (TypeError, ValueError):
        return json.dumps(
            {"ok": False, "error": "start_line and limit_lines must be integers"},
            ensure_ascii=False,
        )
    if limit is not None:
        body = "".join(chunk)
        total = len(lines)
        return json.dumps(
            {
                "ok": True,
                "path": str(rel).replace("\\", "/"),
                "start_line": start,
                "line_count_total": total,
                "content": body,
                "truncated_lines": (start - 1 + len(chunk)) < total,
            },
            ensure_ascii=False,
        )
    if len(lines) > MAX_LINE_READ:
        body = "".join(lines[:MAX_LINE_READ])
        return json.dumps(
            {
                "ok": True,
                "path": str(rel).replace("\\", "/"),
                "content": body,
                "truncated": True,
                "line_count_total": len(lines),
                "max_lines": MAX_LINE_READ,
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": True,
            "path": str(rel).replace("\\", "/"),
            "content": text,
            "truncated": False,
            "line_count_total": len(lines),
        },
        ensure_ascii=False,
    )


def workspace_glob(arguments: dict[str, Any]) -> str:
    pattern = (arguments.get("pattern") or "").strip()
    if not pattern:
        return json.dumps({"ok": False, "error": "pattern is required"}, ensure_ascii=False)
    root = _real_root()
    if not root:
        return json.dumps({"ok": False, "error": _disabled_message()}, ensure_ascii=False)
    if pattern.startswith("/") or ".." in Path(pattern).parts:
        return json.dumps(
            {"ok": False, "error": "pattern must be relative to workspace root"},
            ensure_ascii=False,
        )
    base_rel = (arguments.get("path") or ".").strip() or "."
    base, err = _safe_resolve(base_rel)
    if err:
        return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
    if not os.path.isdir(base):
        return json.dumps({"ok": False, "error": "path is not a directory"}, ensure_ascii=False)

    matches: list[str] = []
    prefix = root + os.sep
    try:
        for p in Path(base).glob(pattern):
            if not p.is_file():
                continue
            try:
                real = os.path.realpath(str(p))
            except OSError:
                continue
            if not (real == root or real.startswith(prefix)):
                continue
            rel_full = os.path.relpath(real, root).replace("\\", "/")
            matches.append(rel_full)
            if len(matches) >= MAX_GLOB_FILES:
                break
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    return json.dumps(
        {
            "ok": True,
            "pattern": pattern,
            "path": base_rel.replace("\\", "/"),
            "files": matches,
            "truncated": len(matches) >= MAX_GLOB_FILES,
            "max_files": MAX_GLOB_FILES,
        },
        ensure_ascii=False,
    )


def workspace_search_text(arguments: dict[str, Any]) -> str:
    query = arguments.get("query")
    if query is None or str(query).strip() == "":
        return json.dumps({"ok": False, "error": "query is required"}, ensure_ascii=False)
    use_regex = bool(arguments.get("regex", False))
    path_prefix = str(arguments.get("path_prefix") or "").strip()
    root = _real_root()
    if not root:
        return json.dumps({"ok": False, "error": _disabled_message()}, ensure_ascii=False)
    search_root = root
    rel_root = ""
    if path_prefix:
        sr, err = _safe_resolve(path_prefix)
        if err:
            return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
        if not os.path.isdir(sr):
            return json.dumps(
                {"ok": False, "error": "path_prefix must be a directory"},
                ensure_ascii=False,
            )
        search_root = sr
        rel_root = path_prefix.replace("\\", "/").rstrip("/")

    try:
        if use_regex:
            cre = re.compile(str(query))
        else:
            needle = str(query)
    except re.error as e:
        return json.dumps({"ok": False, "error": f"invalid regex: {e}"}, ensure_ascii=False)

    matches_out: list[dict[str, Any]] = []
    files_scanned = 0

    def rel_path_from(full: str) -> str:
        rel = os.path.relpath(full, root)
        return rel.replace("\\", "/")

    try:
        for dirpath, _dirnames, filenames in os.walk(search_root):
            for fn in sorted(filenames):
                if len(matches_out) >= MAX_SEARCH_MATCHES:
                    break
                fp = os.path.join(dirpath, fn)
                if not os.path.isfile(fp):
                    continue
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                if st.st_size > SEARCH_MAX_FILE_BYTES:
                    continue
                files_scanned += 1
                if files_scanned > MAX_SEARCH_FILES:
                    break
                try:
                    raw = Path(fp).read_bytes()
                except OSError:
                    continue
                if not _is_probably_text(raw):
                    continue
                text = raw.decode("utf-8", errors="replace")
                lines = text.splitlines()
                for i, line in enumerate(lines, start=1):
                    if len(matches_out) >= MAX_SEARCH_MATCHES:
                        break
                    if use_regex:
                        if not cre.search(line):
                            continue
                    else:
                        if needle not in line:
                            continue
                    matches_out.append(
                        {
                            "path": rel_path_from(fp),
                            "line": i,
                            "text": line if len(line) <= 500 else line[:500] + "…",
                        }
                    )
            if len(matches_out) >= MAX_SEARCH_MATCHES or files_scanned > MAX_SEARCH_FILES:
                break
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    return json.dumps(
        {
            "ok": True,
            "query": str(query),
            "regex": use_regex,
            "path_prefix": rel_root or None,
            "matches": matches_out,
            "files_scanned": files_scanned,
            "truncated_matches": len(matches_out) >= MAX_SEARCH_MATCHES,
            "truncated_scan": files_scanned > MAX_SEARCH_FILES,
            "limits": {
                "max_matches": MAX_SEARCH_MATCHES,
                "max_files_scanned": MAX_SEARCH_FILES,
            },
        },
        ensure_ascii=False,
    )


def workspace_replace_text(arguments: dict[str, Any]) -> str:
    rel = arguments.get("path") or ""
    old = arguments.get("old_string")
    new = arguments.get("new_string")
    if old is None:
        return json.dumps({"ok": False, "error": "old_string is required"}, ensure_ascii=False)
    if new is None:
        new = ""
    path, err = _safe_resolve(str(rel))
    if err:
        return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
    if not os.path.isfile(path):
        return json.dumps(
            {"ok": False, "error": "not a regular file", "path": str(rel)},
            ensure_ascii=False,
        )
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    if len(raw) > MAX_FILE_BYTES:
        return json.dumps({"ok": False, "error": "file too large"}, ensure_ascii=False)
    if not _is_probably_text(raw):
        return json.dumps({"ok": False, "error": "refusing to edit binary file"}, ensure_ascii=False)
    text = raw.decode("utf-8", errors="strict")
    old_s = str(old)
    new_s = str(new)
    count = text.count(old_s)
    if count == 0:
        return json.dumps(
            {"ok": False, "error": "old_string not found", "path": str(rel)},
            ensure_ascii=False,
        )
    try:
        replace_all = bool(arguments.get("replace_all", False))
    except Exception:
        replace_all = False
    if not replace_all and count != 1:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"old_string matches {count} times; set replace_all true to replace all, "
                    "or make old_string unique"
                ),
                "matches": count,
            },
            ensure_ascii=False,
        )
    if replace_all:
        updated = text.replace(old_s, new_s)
        replaced = count
    else:
        updated = text.replace(old_s, new_s, 1)
        replaced = 1
    try:
        Path(path).write_text(updated, encoding="utf-8", newline="")
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "path": str(rel).replace("\\", "/"),
            "replacements": replaced,
            "bytes_written": len(updated.encode("utf-8")),
        },
        ensure_ascii=False,
    )


def workspace_write_file(arguments: dict[str, Any]) -> str:
    rel = arguments.get("path") or ""
    content = arguments.get("content")
    if content is None:
        return json.dumps({"ok": False, "error": "content is required (string)"}, ensure_ascii=False)
    path, err = _safe_resolve(str(rel))
    if err:
        return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
    root = _real_root()
    if not root:
        return json.dumps({"ok": False, "error": _disabled_message()}, ensure_ascii=False)
    text = str(content)
    data = text.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        return json.dumps({"ok": False, "error": "content too large"}, ensure_ascii=False)
    parent = os.path.dirname(path)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    try:
        real_parent = os.path.realpath(parent)
        if not (real_parent == root or real_parent.startswith(root + os.sep)):
            return json.dumps({"ok": False, "error": "parent path outside workspace"}, ensure_ascii=False)
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    try:
        Path(path).write_text(text, encoding="utf-8", newline="")
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "path": str(rel).replace("\\", "/"),
            "bytes_written": len(data),
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "workspace_stat": workspace_stat,
    "workspace_list_dir": workspace_list_dir,
    "workspace_read_file": workspace_read_file,
    "workspace_glob": workspace_glob,
    "workspace_search_text": workspace_search_text,
    "workspace_replace_text": workspace_replace_text,
    "workspace_write_file": workspace_write_file,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "workspace_stat",
            "description": (
                "Metadata for a path inside the mounted workspace (file size, mtime, dir/symlink). "
                "Disabled until AGENT_WORKSPACE_ROOT is set. Not GitHub — use github_get_file for repos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path under workspace root, e.g. README.md or src/foo",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_list_dir",
            "description": (
                "List files and subdirectories under a relative path in the local workspace mount. "
                "Truncates after many entries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory relative to workspace root; use . for root",
                    },
                    "include_files": {
                        "type": "boolean",
                        "description": "Include files (default true)",
                    },
                    "include_directories": {
                        "type": "boolean",
                        "description": "Include directories (default true)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_read_file",
            "description": (
                "Read a UTF-8 text file from the local workspace mount. Optional line window via "
                "start_line and limit_lines. Large files / too many lines are truncated."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path under workspace root"},
                    "start_line": {
                        "type": "integer",
                        "description": "1-based line to start from when limit_lines is set (default 1)",
                    },
                    "limit_lines": {
                        "type": "integer",
                        "description": "If set, return only this many lines from start_line",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_glob",
            "description": (
                "Find file paths under the workspace using a pathlib glob from `path` (e.g. *.py or **/*.md). "
                "Pattern is relative to the base directory; must not start with / or contain .. ."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern relative to workspace, e.g. **/*.nix",
                    },
                    "path": {
                        "type": "string",
                        "description": "Base directory under workspace (default .)",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_search_text",
            "description": (
                "Search file contents under the workspace (substring or regex). Returns path, line number, "
                "and snippet. Skips large and binary files; stops at match/file limits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Literal substring unless regex is true"},
                    "regex": {
                        "type": "boolean",
                        "description": "If true, query is a Python regex",
                    },
                    "path_prefix": {
                        "type": "string",
                        "description": "Optional subdirectory (relative) to limit search scope",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_replace_text",
            "description": (
                "Replace old_string with new_string in a workspace text file. Unless replace_all is true, "
                "old_string must match exactly once. UTF-8 text only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string", "description": "Replacement (may be empty)"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace every occurrence (default false = require single match)",
                    },
                },
                "required": ["path", "old_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_write_file",
            "description": (
                "Create or overwrite a UTF-8 text file under the workspace. Creates parent directories "
                "inside the workspace. Use workspace_replace_text for surgical edits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path under workspace root"},
                    "content": {"type": "string", "description": "Full new file contents"},
                },
                "required": ["path", "content"],
            },
        },
    },
]
