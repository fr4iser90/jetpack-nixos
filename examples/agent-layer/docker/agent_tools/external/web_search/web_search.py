"""Web search: Tavily / Brave (API keys) or ddgs metasearch (no key, unofficial)."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

__version__ = "1.3.1"
TOOL_ID = "web_search"
TOOL_DOMAIN = "web_search"
TOOL_LABEL = "Web search"
TOOL_DESCRIPTION = (
    "Search the web via Tavily, Brave, or DuckDuckGo (ddgs); optional page fetch where allowed."
)
TOOL_TRIGGERS = (
    "web search",
    "search the web",
    "tavily",
    "brave search",
    "duckduckgo",
    "ddgs",
)

_TAVILY_URL = "https://api.tavily.com/search"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.environ.get(key, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _timeout() -> float:
    try:
        return float(os.environ.get("AGENT_SEARCH_TIMEOUT", "45"))
    except ValueError:
        return 45.0


def _max_raw_chars() -> int:
    try:
        return max(1000, int(os.environ.get("AGENT_SEARCH_MAX_RAW_CHARS", "12000")))
    except ValueError:
        return 12000


def _fetch_max_bytes() -> int:
    try:
        return max(50_000, int(os.environ.get("AGENT_FETCH_MAX_BYTES", "2000000")))
    except ValueError:
        return 2_000_000


def _robots_cache_ttl() -> float:
    try:
        return max(60.0, float(os.environ.get("AGENT_ROBOTS_CACHE_TTL", "3600")))
    except ValueError:
        return 3600.0


def _fetch_domain_allowlist() -> frozenset[str] | None:
    raw = os.environ.get("AGENT_FETCH_DOMAIN_ALLOWLIST", "").strip()
    if not raw:
        return None
    parts: list[str] = []
    for p in raw.split(","):
        s = p.strip().lower().strip(".")
        if s:
            parts.append(s)
    return frozenset(parts) if parts else None


def _hostname_matches_allowlist(host: str, allow: frozenset[str]) -> bool:
    h = host.lower().rstrip(".")
    if not h:
        return False
    if h in allow:
        return True
    for d in allow:
        if h.endswith("." + d):
            return True
    return False


def _directives_request_noindex(directives: str) -> bool:
    """True if noindex or none (common shorthand for noindex,nofollow)."""
    if not directives.strip():
        return False
    tokens = {t for t in re.split(r"[\s,;]+", directives.lower()) if t}
    return "noindex" in tokens or "none" in tokens


def _x_robots_tag_requests_noindex(header_val: str) -> bool:
    if not header_val or not header_val.strip():
        return False
    for part in header_val.split(","):
        if _directives_request_noindex(part):
            return True
    return False


def _html_meta_robots_noindex(html: str) -> bool:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for m in soup.find_all("meta"):
        name = (m.get("name") or "").strip().lower()
        if name != "robots":
            continue
        if _directives_request_noindex(m.get("content") or ""):
            return True
    return False


def _clamp_results(n: Any, default: int, hi: int = 15) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = default
    return max(1, min(v, hi))


def _trim_result_fields(results: list[dict[str, Any]], max_chars: int) -> None:
    for item in results:
        if not isinstance(item, dict):
            continue
        for key in ("content", "raw_content", "snippet"):
            val = item.get(key)
            if isinstance(val, str) and len(val) > max_chars:
                item[key] = val[:max_chars] + "…"


def _tavily_search(
    query: str,
    *,
    search_depth: str,
    max_results: int,
    include_raw_content: bool,
) -> dict[str, Any]:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TAVILY_API_KEY not set")
    payload: dict[str, Any] = {
        "api_key": key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_raw_content": include_raw_content,
        "include_answer": True,
    }
    with httpx.Client(timeout=_timeout()) as client:
        r = client.post(_TAVILY_URL, json=payload)
        r.raise_for_status()
        return r.json()


def _brave_search(query: str, count: int) -> dict[str, Any]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY not set")
    with httpx.Client(timeout=_timeout()) as client:
        r = client.get(
            _BRAVE_URL,
            params={"q": query, "count": count},
            headers={
                "X-Subscription-Token": key,
                "Accept": "application/json",
            },
        )
        r.raise_for_status()
        return r.json()


def _normalize_brave(data: dict[str, Any]) -> dict[str, Any]:
    web = data.get("web") or {}
    rows = web.get("results") or []
    out = []
    for w in rows:
        if not isinstance(w, dict):
            continue
        out.append(
            {
                "title": w.get("title"),
                "url": w.get("url"),
                "content": w.get("TOOL_DESCRIPTION") or "",
            }
        )
    return {"engine": "brave", "answer": None, "results": out}


def _ddg_search(query: str, max_results: int) -> dict[str, Any]:
    """Metasearch via ``ddgs`` (no API key); backends may include Bing/DuckDuckGo/etc."""
    if _env_bool("AGENT_DISABLE_DDG_SEARCH"):
        raise RuntimeError("ddgs fallback disabled (AGENT_DISABLE_DDG_SEARCH)")
    from ddgs import DDGS

    to = max(5, min(int(_timeout()), 120))
    out: list[dict[str, Any]] = []
    rows = DDGS(timeout=to).text(query, max_results=max_results)
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "title": r.get("title"),
                "url": r.get("href"),
                "content": r.get("body") or "",
            }
        )
    return {"engine": "ddgs", "answer": None, "results": out}


_ROBOTS_LOCK = threading.Lock()
_ROBOTS_CACHE: dict[str, tuple[RobotFileParser, float]] = {}
_CRAWL_LOCK = threading.Lock()
_LAST_FETCH_BY_ORIGIN: dict[str, float] = {}


def _fetch_user_agent() -> str:
    return (
        os.environ.get("AGENT_FETCH_USER_AGENT", "").strip()
        or "JetpackAgentLayer/1.0 (respects robots.txt; private use)"
    )


def _allow_all_robots_parser() -> RobotFileParser:
    rp = RobotFileParser()
    rp.set_url("https://invalid.local/robots.txt")
    rp.parse(["User-agent: *", "Disallow:"])
    return rp


def _deny_all_robots_parser() -> RobotFileParser:
    rp = RobotFileParser()
    rp.set_url("https://invalid.local/robots.txt")
    rp.parse(["User-agent: *", "Disallow: /"])
    return rp


def _origin_from_page_url(url: str) -> str | None:
    p = urlparse(url.strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}"


def _url_host_safe(url: str) -> tuple[bool, str]:
    """Block obvious SSRF (loopback, link-local, metadata)."""
    try:
        p = urlparse(url.strip())
    except Exception:
        return False, "bad_url"
    if p.scheme not in ("http", "https"):
        return False, "blocked_scheme"
    host = (p.hostname or "").lower()
    if not host:
        return False, "blocked_scheme"
    if host == "localhost" or host.endswith(".localhost"):
        return False, "blocked_ssrf"
    if host in ("metadata.google.internal", "metadata.goog"):
        return False, "blocked_ssrf"
    h = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False, "blocked_ssrf"
    except ValueError:
        pass
    if re.match(r"^(127\.|169\.254\.)", host):
        return False, "blocked_ssrf"
    return True, ""


def _robots_url_for_origin(origin: str) -> str:
    return origin.rstrip("/") + "/robots.txt"


def _get_or_load_robots_parser(origin: str, client: httpx.Client) -> RobotFileParser:
    strict = _env_bool("AGENT_ROBOTS_STRICT", False)
    ttl = _robots_cache_ttl()
    now = time.time()
    with _ROBOTS_LOCK:
        ent = _ROBOTS_CACHE.get(origin)
        if ent is not None:
            rp, ts = ent
            if now - ts < ttl:
                return rp
    robots_url = _robots_url_for_origin(origin)
    rp_loaded: RobotFileParser | None = None
    try:
        r = client.get(robots_url, follow_redirects=True, timeout=min(15.0, _timeout()))
        if r.status_code == 200:
            rp_new = RobotFileParser()
            rp_new.set_url(robots_url)
            rp_new.parse(r.text.splitlines())
            rp_loaded = rp_new
        elif r.status_code in (401, 403, 404):
            rp_loaded = _allow_all_robots_parser()
        else:
            rp_loaded = None
    except Exception:
        rp_loaded = None
    if rp_loaded is None:
        rp_loaded = _deny_all_robots_parser() if strict else _allow_all_robots_parser()
    with _ROBOTS_LOCK:
        _ROBOTS_CACHE[origin] = (rp_loaded, now)
    return rp_loaded


def _respect_crawl_delay(origin: str, rp: RobotFileParser, ua: str) -> None:
    delay: float | None = None
    try:
        d = rp.crawl_delay(ua)
        if d is not None and d > 0:
            delay = float(d)
    except Exception:
        pass
    if delay is None:
        return
    with _CRAWL_LOCK:
        last = _LAST_FETCH_BY_ORIGIN.get(origin, 0.0)
        wait = delay - (time.time() - last)
        if wait > 0:
            time.sleep(min(wait, 60.0))


def _mark_fetched(origin: str) -> None:
    with _CRAWL_LOCK:
        _LAST_FETCH_BY_ORIGIN[origin] = time.time()


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [ln for ln in (x.strip() for x in text.splitlines()) if ln]
    return "\n".join(lines)


def _fetch_page_text_respecting_robots(
    url: str,
    *,
    max_chars: int,
    client: httpx.Client,
) -> tuple[str, str | None]:
    """Returns (status, text_or_none)."""
    ok, why = _url_host_safe(url)
    if not ok:
        return why, None
    origin = _origin_from_page_url(url)
    if not origin:
        return "blocked_scheme", None
    try:
        page_host = (urlparse(url.strip()).hostname or "").lower()
    except Exception:
        page_host = ""
    allow = _fetch_domain_allowlist()
    if allow is not None and not _hostname_matches_allowlist(page_host, allow):
        return "blocked_allowlist", None
    ua = _fetch_user_agent()
    try:
        rp = _get_or_load_robots_parser(origin, client)
    except Exception as e:
        return f"robots_error:{e}", None
    try:
        if not rp.can_fetch(ua, url):
            return "robots_disallowed", None
    except Exception as e:
        return f"robots_error:{e}", None
    _respect_crawl_delay(origin, rp, ua)
    max_bytes = _fetch_max_bytes()
    try:
        with client.stream(
            "GET",
            url,
            headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
            timeout=_timeout(),
        ) as r:
            r.raise_for_status()
            if _env_bool("AGENT_RESPECT_META_ROBOTS", True):
                xrt = r.headers.get("x-robots-tag")
                if xrt and _x_robots_tag_requests_noindex(xrt):
                    return "x_robots_noindex", None
            chunks: list[bytes] = []
            total = 0
            for chunk in r.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                chunks.append(chunk)
                if total >= max_bytes:
                    break
        body = b"".join(chunks)
        if not body:
            return "empty_body", None
        html = body.decode("utf-8", errors="replace")
        if _env_bool("AGENT_RESPECT_META_ROBOTS", True) and _html_meta_robots_noindex(
            html
        ):
            return "meta_robots_noindex", None
        text = _html_to_text(html)
        if not text.strip():
            return "empty_body", None
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        _mark_fetched(origin)
        return "ok", text
    except Exception as e:
        return f"fetch_error:{e}", None


def _enrich_results_with_fetched_text(
    results: list[dict[str, Any]],
    *,
    max_page_fetches: int,
    max_chars: int,
) -> None:
    if max_page_fetches <= 0:
        return
    attempted = 0
    to = _timeout()
    with httpx.Client(timeout=to, trust_env=False) as client:
        for item in results:
            if attempted >= max_page_fetches:
                break
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            attempted += 1
            status, raw = _fetch_page_text_respecting_robots(
                url.strip(), max_chars=max_chars, client=client
            )
            item["fetch_status"] = status
            if raw is not None:
                item["raw_content"] = raw


def search_web(arguments: dict[str, Any]) -> str:
    query = (arguments.get("query") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query is empty"})
    max_results = _clamp_results(arguments.get("max_results"), 5, 15)

    tavily_err: str | None = None
    if os.environ.get("TAVILY_API_KEY", "").strip():
        try:
            raw = _tavily_search(
                query,
                search_depth="basic",
                max_results=max_results,
                include_raw_content=False,
            )
            results = list(raw.get("results") or [])
            _trim_result_fields(results, 4000)
            return json.dumps(
                {
                    "ok": True,
                    "engine": "tavily",
                    "mode": "search",
                    "answer": raw.get("answer"),
                    "results": results,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            tavily_err = str(e)

    brave_err: str | None = None
    try:
        raw = _brave_search(query, max_results)
        norm = _normalize_brave(raw)
        _trim_result_fields(norm["results"], 4000)
        out: dict[str, Any] = {"ok": True, **norm, "mode": "search"}
        if tavily_err:
            out["note"] = f"Tavily failed, used Brave instead: {tavily_err}"
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        brave_err = str(e)

    try:
        norm = _ddg_search(query, max_results)
        _trim_result_fields(norm["results"], 4000)
        out2: dict[str, Any] = {
            "ok": True,
            **norm,
            "mode": "search",
            "note": (
                "No API keys: using ddgs metasearch (unofficial, snippets only). "
                "Set TAVILY_API_KEY or BRAVE_SEARCH_API_KEY for more reliable search."
            ),
        }
        if tavily_err:
            out2["tavily_error"] = tavily_err
        if brave_err:
            out2["brave_error"] = brave_err
        return json.dumps(out2, ensure_ascii=False)
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "error": f"ddgs: {e}",
                "tavily_error": tavily_err,
                "brave_error": brave_err,
                "hint": "Fix API keys or ddgs; set AGENT_DISABLE_DDG_SEARCH=false (default).",
            },
            ensure_ascii=False,
        )


def deep_search(arguments: dict[str, Any]) -> str:
    query = (arguments.get("query") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "query is empty"})
    max_results = _clamp_results(arguments.get("max_results"), 5, 10)
    max_chars = _clamp_results(
        arguments.get("max_chars_per_source"), _max_raw_chars(), hi=50000
    )

    tavily_err: str | None = None
    if os.environ.get("TAVILY_API_KEY", "").strip():
        try:
            raw = _tavily_search(
                query,
                search_depth="advanced",
                max_results=max_results,
                include_raw_content=True,
            )
            results = list(raw.get("results") or [])
            _trim_result_fields(results, max_chars)
            return json.dumps(
                {
                    "ok": True,
                    "engine": "tavily",
                    "mode": "deep",
                    "answer": raw.get("answer"),
                    "results": results,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            tavily_err = str(e)

    brave_err: str | None = None
    norm: dict[str, Any] | None = None
    try:
        raw = _brave_search(query, min(max_results + 5, 20))
        norm = _normalize_brave(raw)
    except Exception as e:
        brave_err = str(e)

    if norm is None:
        try:
            norm = _ddg_search(query, min(max_results + 5, 15))
        except Exception as e:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"ddgs: {e}",
                    "tavily_error": tavily_err,
                    "brave_error": brave_err,
                    "hint": "Enable ddgs or set BRAVE_SEARCH_API_KEY / TAVILY_API_KEY.",
                },
                ensure_ascii=False,
            )

    _trim_result_fields(norm["results"], 6000)
    fetch_disabled = _env_bool("AGENT_DISABLE_FETCH_DEEP", False)
    if not fetch_disabled:
        _enrich_results_with_fetched_text(
            norm["results"],
            max_page_fetches=max_results,
            max_chars=max_chars,
        )
        _trim_result_fields(norm["results"], max_chars)
        note = (
            "Snippet hits + page text where robots.txt allows this user-agent (no Tavily). "
            "Skips index when X-Robots-Tag or meta robots says noindex/none (AGENT_RESPECT_META_ROBOTS). "
            "Optional host allowlist: AGENT_FETCH_DOMAIN_ALLOWLIST. "
            "Each result: fetch_status, raw_content if ok. "
            "AGENT_ROBOTS_STRICT / AGENT_DISABLE_FETCH_DEEP see TOOLS.md."
        )
        mode = "deep_fetch"
    else:
        note = (
            "Snippet-only (fetch disabled). Set AGENT_DISABLE_FETCH_DEEP=false to fetch pages "
            "when robots.txt allows, or set TAVILY_API_KEY for hosted extraction."
        )
        mode = "deep_fallback"

    out: dict[str, Any] = {
        "ok": True,
        **norm,
        "mode": mode,
        "note": note,
    }
    if tavily_err:
        out["tavily_error"] = tavily_err
    if brave_err:
        out["brave_error"] = brave_err
    return json.dumps(out, ensure_ascii=False)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "search_web": search_web,
    "deep_search": deep_search,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "TOOL_DESCRIPTION": (
                "Search the public web (titles, URLs, snippets). "
                "Uses Tavily if TAVILY_API_KEY is set, else Brave if BRAVE_SEARCH_API_KEY is set, "
                "else ddgs metasearch without any API key (unofficial, less reliable)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "TOOL_DESCRIPTION": "Search query"},
                    "max_results": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max results (1–15, default 5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deep_search",
            "TOOL_DESCRIPTION": (
                "Richer research: with TAVILY_API_KEY uses advanced search + extracted page text. "
                "Without Tavily: web snippets then fetches pages when robots.txt allows this agent's "
                "User-Agent (see fetch_status per result; AGENT_DISABLE_FETCH_DEEP to turn off)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Research question or keywords",
                    },
                    "max_results": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max sources (1–10, default 5)",
                    },
                    "max_chars_per_source": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Truncate each snippet/raw_content (default from AGENT_SEARCH_MAX_RAW_CHARS)",
                    },
                },
                "required": ["query"],
            },
        },
    },
]
