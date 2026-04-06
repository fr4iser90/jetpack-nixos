"""Chat completion with tool-call loop; HTTP to Ollama uses the OpenAI-compatible wire format only."""

from __future__ import annotations

import json
import logging
import re
import uuid
from json import JSONDecoder
from typing import Any

import httpx

from . import config
from .registry import get_registry
from .tool_routing import (
    TOOL_INTROSPECTION,
    classify_user_tool_categories,
    filter_merged_tools_by_categories,
    filter_merged_tools_by_domain,
    last_user_text,
)
from .tools import run_tool

logger = logging.getLogger(__name__)


def _http_error_recovery_hint(tool_name: str, result: str) -> str | None:
    if not config.AGENT_TOOL_HTTP_ERROR_RECOVERY_HINTS:
        return None
    if len(result) > 8000:
        return None
    rl = result.lower()
    markers = (
        "http error",
        "bad request",
        "401 unauthorized",
        "403 forbidden",
        "404 not found",
        " 400 ",
        "'400'",
        '"400"',
        "status 400",
        "status 401",
        "status 403",
        "status 404",
        "httpx",
        "for url 'http",
        'for url "http',
    )
    if not any(m in rl for m in markers):
        return None
    fix_strategy = (
        "For a **one-line API fix** (wrong query param, URL), **`update_tool`** is usually enough; "
        "use **`replace_tool`** if you need a larger rewrite. "
    )
    return (
        "The previous tool output suggests an HTTP/API failure. "
        "Do not blame the API key first: **400 Bad Request** often means **wrong query parameters** "
        "(e.g. OpenWeather `/data/2.5/weather` expects **`q`** for the place name, not `city`). "
        "**401** more often means an invalid or missing key. "
        + fix_strategy
        + "Next steps: (1) **`read_tool`** the `.py` for this tool (use `registered_tool_name` "
        f"{tool_name!r} or `filename`). (2) Optionally **`search_web`** for the vendor's current API docs. "
        "(3) Apply the fix with **`replace_tool`** and/or **`update_tool`**; use **`https://`**. "
        "(4) Or delegate to built-ins: **`invoke_registered_tool`**(`\"openweather_current\"`, "
        "`{\"location\": \"…\"}`) / `openweather_forecast` from Python in an extra tool."
    )


# Client-only keys: never forward to Ollama (not in upstream Chat Completions request schema).
_BODY_KEYS_STRIP_FROM_OLLAMA = frozenset(
    {"tool_prefetch", "agent_router_categories", "TOOL_DOMAIN"}
)


def _parse_router_category_tokens(raw: str | None) -> frozenset[str]:
    if not raw or not str(raw).strip():
        return frozenset()
    return frozenset(x.strip().lower() for x in str(raw).split(",") if x.strip())


def _parse_router_categories_value(raw: Any) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        return _parse_router_category_tokens(raw)
    if isinstance(raw, list):
        return frozenset(str(x).strip().lower() for x in raw if str(x).strip())
    return frozenset()


def _inject_system_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not config.SYSTEM_PROMPT_EXTRA:
        return messages
    extra = config.SYSTEM_PROMPT_EXTRA
    if not messages:
        return [{"role": "system", "content": extra}]
    out = list(messages)
    if out[0].get("role") == "system":
        existing = out[0].get("content") or ""
        out[0] = {
            **out[0],
            "content": (existing + "\n\n" + extra).strip() if existing else extra,
        }
    else:
        out.insert(0, {"role": "system", "content": extra})
    return out


def _tool_spec_name(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    fn = entry.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        return str(n) if n else None
    return None


def _merge_tools(body_tools: list[Any] | None) -> list[Any]:
    """
    Always merge the live registry tool list into the request for Ollama.

    Open WebUI often sends its own non-empty ``tools`` list; previously that
    replaced our list entirely so the model never saw agent-layer tools.
    """
    ours = get_registry().chat_tool_specs
    if not body_tools:
        return ours
    seen = {n for t in ours if (n := _tool_spec_name(t))}
    merged: list[Any] = list(ours)
    for t in body_tools:
        if not isinstance(t, dict):
            continue
        n = _tool_spec_name(t)
        if n is None:
            merged.append(t)
            continue
        if n not in seen:
            merged.append(t)
            seen.add(n)
    logger.debug(
        "tools merge: registry=%d client=%d merged=%d",
        len(ours),
        len(body_tools),
        len(merged),
    )
    return merged


_CATALOG_PARAM_HINT = (
    "Full JSON parameter schema is not inlined here. Call get_tool_help with tool_name set to this "
    "tool's name, then invoke with arguments matching that schema."
)


def _catalog_tool_function(name: str, fn: dict[str, Any]) -> dict[str, Any]:
    """Small tools[] entry: TOOL_LABEL + TOOL_DESCRIPTION hint; minimal parameters (never full domain schemas)."""
    desc = (fn.get("TOOL_DESCRIPTION") or "").strip()
    if _CATALOG_PARAM_HINT not in desc:
        desc = f"{desc}\n\n{_CATALOG_PARAM_HINT}".strip() if desc else _CATALOG_PARAM_HINT
    if name == "get_tool_help":
        params: dict[str, Any] = {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "TOOL_DESCRIPTION": "Exact tool name from list_tools_in_category or list_available_tools",
                },
            },
            "required": ["tool_name"],
        }
    elif name == "list_tools_in_category":
        params = {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "TOOL_DESCRIPTION": "Category id from list_tool_categories",
                },
            },
            "required": ["category"],
        }
    else:
        params = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
    return {
        "type": "function",
        "function": {
            "name": name,
            "TOOL_DESCRIPTION": desc,
            "parameters": params,
        },
    }


def _tools_for_chat_request(merged_tools: list[Any]) -> list[Any]:
    """
    Build tools[] for Ollama: **nur Katalog-Einträge** (Name, Kurzbeschreibung, minimale parameters).

    **Volles** JSON-Schema für ein Domänen-Tool gibt es **nicht** in ``tools[]`` — nur in der
    **Tool-Antwort** von ``get_tool_help(tool_name)`` (stufenweise Erkundung).
    """
    out: list[Any] = []
    for spec in merged_tools:
        if not isinstance(spec, dict):
            out.append(spec)
            continue
        name = _tool_spec_name(spec)
        fn = spec.get("function")
        if not name or not isinstance(fn, dict):
            out.append(spec)
            continue
        out.append(_catalog_tool_function(name, fn))
    return out


def _tools_payload_size_estimate(tools: list[Any]) -> tuple[int, int, int]:
    """
    (json_char_count, est_tokens_low, est_tokens_high) for the tools[] array as sent in the request.

    Heuristic only: chars/4 .. chars/3 — not the model tokenizer; real usage depends on the backend.
    """
    if not tools:
        return 0, 0, 0
    raw = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    c = len(raw)
    lo = (c + 3) // 4
    hi = (c + 2) // 3
    return c, lo, hi


def _log_tools_request_estimate(TOOL_LABEL: str, tools: list[Any]) -> None:
    if not config.AGENT_LOG_TOOLS_REQUEST_ESTIMATE:
        return
    n = len(tools)
    jc, lo, hi = _tools_payload_size_estimate(tools)
    logger.info(
        "tools request %s: tool_defs=%d json_chars=%d est_tokens~%d-%d (heuristic, not tokenizer)",
        TOOL_LABEL,
        n,
        jc,
        lo,
        hi,
    )


def _parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("invalid tool arguments JSON: %s", raw[:200])
        return {}


def _unwrap_fenced_json(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if not lines:
        return t
    lines = lines[1:]
    while lines and lines[-1].strip() in ("```", ""):
        lines.pop()
    return "\n".join(lines).strip()


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _end = JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _strip_model_output_markers(text: str) -> str:
    """
    Remove whole-line angle-bracket sentinels some models emit (e.g. Nemotron
    ``<｜begin▁of▁string>`` / ``<｜end▁of▁string>``) so ``replace_tool({...})`` prose can be parsed.
    """
    lines_out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if len(s) >= 3 and s[0] == "<" and s[-1] == ">" and "\n" not in s:
            inner = s[1:-1].lower()
            if any(
                needle in inner
                for needle in (
                    "begin",
                    "end",
                    "start",
                    "eof",
                    "eot",
                    "string",
                    "think",
                    "reasoning",
                )
            ):
                continue
        lines_out.append(line)
    return "\n".join(lines_out).strip()


def _parse_parenthesized_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """
    Parse ``read_tool({...})`` / ``replace_tool({...})`` style text when the model
    does not emit native ``tool_calls`` (common with small Nemotron builds).
    """
    names = sorted(_CONTENT_META_TOOL_NAMES, key=len, reverse=True)
    for name in names:
        key = name + "("
        pos = 0
        while True:
            idx = text.find(key, pos)
            if idx < 0:
                break
            j = idx + len(key)
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j >= len(text) or text[j] != "{":
                pos = idx + 1
                continue
            try:
                obj, _end = JSONDecoder().raw_decode(text[j:])
            except json.JSONDecodeError:
                pos = idx + 1
                continue
            if isinstance(obj, dict):
                return name, obj
            pos = idx + 1
    return None


def _known_tool_names() -> set[str]:
    return {n for t in get_registry().chat_tool_specs if (n := _tool_spec_name(t))}


def _coerce_params_dict(p: Any) -> dict[str, Any] | None:
    if p is None:
        return {}
    if isinstance(p, dict):
        return p
    if isinstance(p, str):
        s = p.strip()
        if not s:
            return {}
        try:
            o = json.loads(s)
        except json.JSONDecodeError:
            return None
        return dict(o) if isinstance(o, dict) else None
    return None


# JSON where the function name is under ``tool_name`` (Nemotron) instead of ``name`` / ``tool``.
_CONTENT_META_TOOL_NAMES = frozenset(
    {
        "read_tool",
        "replace_tool",
        "create_tool",
        "update_tool",
        "rename_tool",
        "list_tools",
        "list_available_tools",
        "get_tool_help",
    }
)

# Models often put filename/source at the JSON root while using "tool"/"name" instead of nested parameters.
_CONTENT_META_TOP_LEVEL_ARG_KEYS = (
    "filename",
    "registered_tool_name",
    "tool_name",
    "name",
    "source",
    "old_string",
    "new_string",
    "replace_all",
    "old_filename",
    "new_filename",
    "overwrite",
    "TOOL_DESCRIPTION",
)


def _merge_meta_tool_obj_args(name: str, obj: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    if name not in _CONTENT_META_TOOL_NAMES:
        return base
    out = dict(base)
    if isinstance(obj.get("parameters"), dict):
        out.update(obj["parameters"])
    if isinstance(obj.get("arguments"), dict):
        out.update(obj["arguments"])
    for k in _CONTENT_META_TOP_LEVEL_ARG_KEYS:
        if k in obj:
            out[k] = obj[k]
    return out


def _parse_tool_intent_from_content(content: str) -> tuple[str, dict[str, Any]] | None:
    """
    Some models emit JSON like {\"tool\": \"<name>\", \"parameters\": {...}} in message content
    instead of wire-format ``tool_calls``.
    """
    t = _strip_model_output_markers(_unwrap_fenced_json(content))
    pc = _parse_parenthesized_tool_call(t)
    if pc:
        return pc
    obj = _extract_first_json_object(t)
    if not obj:
        return None
    name: str | None = None
    params: dict[str, Any] | None = None
    tnk = obj.get("tool_name")
    if isinstance(tnk, str) and tnk.strip() in _CONTENT_META_TOOL_NAMES:
        name = tnk.strip()
        params = {k: v for k, v in obj.items() if k != "tool_name"}
        params = _merge_meta_tool_obj_args(name, obj, params)
        return name, params
    if isinstance(obj.get("tool"), str):
        name = str(obj["tool"]).strip()
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        if not isinstance(p, dict):
            p = obj.get("params")
        params = _coerce_params_dict(p)
    elif isinstance(obj.get("name"), str):
        name = str(obj["name"]).strip()
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        if not isinstance(p, dict):
            p = obj.get("params")
        params = _coerce_params_dict(p)
    elif isinstance(obj.get("function"), str):
        name = str(obj["function"]).strip()
        p = obj.get("parameters")
        if not isinstance(p, dict):
            p = obj.get("arguments")
        if not isinstance(p, dict):
            p = obj.get("params")
        params = _coerce_params_dict(p)
    if not name or params is None:
        return None
    if isinstance(params, dict):
        params = _merge_meta_tool_obj_args(name, obj, params)
    return name, params


def _content_fallback_args_acceptable(name: str, params: dict[str, Any]) -> bool:
    """Reject synthetic tool_calls that would no-op or loop (e.g. read_tool({}))."""
    if name == "read_tool":
        return any(
            str(params.get(k) or "").strip()
            for k in ("filename", "registered_tool_name", "tool_name", "name")
        )
    if name == "replace_tool":
        if not str(params.get("source") or "").strip():
            return False
        return any(
            str(params.get(k) or "").strip()
            for k in ("filename", "registered_tool_name", "tool_name", "name")
        )
    if name == "update_tool":
        if not str(params.get("old_string") or "").strip():
            return False
        return any(
            str(params.get(k) or "").strip()
            for k in ("filename", "registered_tool_name", "tool_name", "name")
        )
    if name == "create_tool":
        if str(params.get("source") or "").strip():
            return True
        return bool(str(params.get("tool_name") or "").strip() or str(params.get("name") or "").strip())
    if name == "rename_tool":
        return bool(str(params.get("old_filename") or "").strip()) and bool(
            str(params.get("new_filename") or "").strip()
        )
    if name == "get_tool_help":
        return bool(str(params.get("tool_name") or "").strip())
    return True


def _text_blobs_from_message(msg: dict[str, Any]) -> list[str]:
    """Collect strings where models may hide JSON tool intent (reasoning models, multimodal content)."""
    blobs: list[str] = []
    t = msg.get("text")
    if isinstance(t, str) and t.strip():
        blobs.append(t)
    c = msg.get("content")
    if isinstance(c, str) and c.strip():
        blobs.append(c)
    elif isinstance(c, list):
        for part in c:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    blobs.append(part["text"])
                elif isinstance(part.get("content"), str):
                    blobs.append(part["content"])
            elif isinstance(part, str):
                blobs.append(part)
    for key in (
        "reasoning_content",
        "reasoning",
        "thinking",
        "thought",
        "reasoning_content_delta",  # some proxies
    ):
        v = msg.get(key)
        if isinstance(v, str) and v.strip():
            blobs.append(v)
    return blobs


def _synthetic_tool_calls_from_message(
    msg: dict[str, Any],
    choice: dict[str, Any] | None = None,
    *,
    allowed_tool_names: set[str] | None = None,
) -> list[dict[str, Any]] | None:
    if not config.CONTENT_TOOL_FALLBACK:
        return None
    if msg.get("tool_calls"):
        return None
    known = allowed_tool_names if allowed_tool_names is not None else _known_tool_names()
    blobs = _text_blobs_from_message(msg)
    if choice:
        for key in ("thought", "reasoning", "thinking"):
            v = choice.get(key)
            if isinstance(v, str) and v.strip():
                blobs.append(v)
    for blob in blobs:
        parsed = _parse_tool_intent_from_content(blob)
        if not parsed:
            continue
        name, params = parsed
        if name not in known:
            logger.debug("content tool JSON names unknown tool %r, ignoring", name)
            continue
        if not _content_fallback_args_acceptable(name, params):
            logger.info(
                "content tool fallback: reject %s with insufficient args %r (avoid empty read_tool loop)",
                name,
                params,
            )
            continue
        tc = {
            "id": f"content-{uuid.uuid4().hex[:16]}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(params)},
        }
        logger.info(
            "content tool fallback: synthetic tool_calls for %s(%s) (JSON or parenthesized prose)",
            name,
            params,
        )
        return [tc]
    logger.debug(
        "content tool fallback: no tool JSON found (message keys=%s, blobs=%d)",
        list(msg.keys()),
        len(blobs),
    )
    return None


def _apply_tool_prefetch(messages: list[dict[str, Any]], prefetch: dict[str, Any]) -> None:
    args = {
        k: prefetch[k]
        for k in ("filename", "registered_tool_name", "tool_name", "name")
        if k in prefetch and prefetch[k] is not None and str(prefetch[k]).strip()
    }
    if not args:
        return
    snippet = run_tool("read_tool", args)
    try:
        o = json.loads(snippet)
    except json.JSONDecodeError:
        o = {}
    if isinstance(o, dict) and o.get("ok") is True:
        src = str(o.get("source") or "")
        max_c = min(len(src), config.CREATE_TOOL_MAX_BYTES)
        block = (
            "Server prefetch via read_tool — edit this **extra-tool module** with read_tool/update_tool/replace_tool "
            "(not workspace_*).\n\n"
            f"File: `{o.get('filename')}`\n\n```python\n{src[:max_c]}\n```"
        )
    else:
        err = o.get("error") if isinstance(o, dict) else snippet[:500]
        block = f"Server prefetch read_tool failed: {err}"
    if not messages:
        messages.append({"role": "system", "content": block})
        return
    if messages[0].get("role") == "system":
        prev = messages[0].get("content") or ""
        messages[0] = {
            **messages[0],
            "content": (block + "\n\n" + prev).strip() if prev else block,
        }
    else:
        messages.insert(0, {"role": "system", "content": block})


def _names_from_tool_list(tools: list[Any]) -> set[str]:
    return {n for t in tools if (n := _tool_spec_name(t))}


def _approx_text_chars_in_messages(messages: list[dict[str, Any]]) -> int:
    return sum(sum(len(b) for b in _text_blobs_from_message(m)) for m in messages)


def _redact_secrets_for_log(s: str) -> str:
    """Best-effort masking for log previews (OpenWeather appid, Bearer tokens)."""
    s = re.sub(r"(?i)appid=[A-Za-z0-9._-]+", "appid=***", s)
    s = re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer ***", s)
    return s


def _log_ollama_round(
    *,
    round_i: int,
    model: Any,
    messages: list[dict[str, Any]],
    tools_for_round: list[Any],
    msg: dict[str, Any],
    choice0: dict[str, Any],
    tool_calls: list[Any] | None,
    had_native_tool_calls: bool,
) -> None:
    if not config.AGENT_LOG_LLM_ROUNDS:
        return
    ctx_msgs = len(messages)
    ctx_chars = _approx_text_chars_in_messages(messages)
    large = ""
    if ctx_chars >= config.AGENT_LOG_LARGE_CONTEXT_CHARS:
        large = f" LARGE_CTX(>={config.AGENT_LOG_LARGE_CONTEXT_CHARS} chars)"
    rt_names = [n for t in (tools_for_round or []) if (n := _tool_spec_name(t))]
    syn = bool(tool_calls) and not had_native_tool_calls
    if tool_calls:
        call_names = [(tc.get("function") or {}).get("name") or "?" for tc in tool_calls]
        logger.info(
            "llm round %d/%d model=%s reply=TOOLS calls=%s content_json_fallback=%s "
            "ctx_msgs=%d ctx_text_chars~=%d ollama_tool_defs=%d tool_names=%s%s",
            round_i + 1,
            config.MAX_TOOL_ROUNDS,
            model,
            call_names,
            syn,
            ctx_msgs,
            ctx_chars,
            len(rt_names),
            rt_names,
            large,
        )
        return
    cap = config.AGENT_LOG_ASSISTANT_PREVIEW_CHARS
    blobs = list(_text_blobs_from_message(msg))
    for key in ("thought", "reasoning", "thinking"):
        v = choice0.get(key)
        if isinstance(v, str) and v.strip():
            blobs.append(v)
    joined = "\n".join(blobs)
    any_text = bool(joined.strip())
    if cap > 0:
        preview = _redact_secrets_for_log(joined[:cap])
    else:
        preview = "(set AGENT_LOG_ASSISTANT_PREVIEW_CHARS>0 for redacted snippet)"
    if not any_text:
        logfn = logger.warning if rt_names else logger.info
        logfn(
            "llm round %d/%d model=%s reply=EMPTY_NO_TOOLS content_json_fallback=%s "
            "ctx_msgs=%d ctx_text_chars~=%d ollama_tool_defs=%d%s",
            round_i + 1,
            config.MAX_TOOL_ROUNDS,
            model,
            syn,
            ctx_msgs,
            ctx_chars,
            len(rt_names),
            large,
        )
        return
    logger.info(
        "llm round %d/%d model=%s reply=TEXT_NO_TOOLS content_json_fallback=%s "
        "ctx_msgs=%d ctx_text_chars~=%d ollama_tool_defs=%d preview=%r%s",
        round_i + 1,
        config.MAX_TOOL_ROUNDS,
        model,
        syn,
        ctx_msgs,
        ctx_chars,
        len(rt_names),
        preview,
        large,
    )


async def chat_completion(
    body: dict[str, Any],
    *,
    router_categories_header: str | None = None,
    tool_domain_header: str | None = None,
) -> dict[str, Any]:
    # stream flag is ignored here; Ollama always gets stream=false. Caller may wrap JSON as SSE.
    body.pop("agent_tool_mode", None)
    body.pop("agent_mode", None)
    extra_cats_body = _parse_router_categories_value(body.pop("agent_router_categories", None))
    extra_cats_hdr = _parse_router_category_tokens(router_categories_header)
    raw_tool_dom = body.pop("TOOL_DOMAIN", None)
    body_tool_dom = (
        str(raw_tool_dom).strip().lower()
        if isinstance(raw_tool_dom, str) and raw_tool_dom.strip()
        else ""
    )
    hdr_tool_dom = (tool_domain_header or "").strip().lower()
    tool_domain = hdr_tool_dom or body_tool_dom or None

    from .config import OLLAMA_DEFAULT_MODEL
    model = body.get("model", OLLAMA_DEFAULT_MODEL)

    messages = _inject_system_prompt(list(body.get("messages") or []))
    pf = body.get("tool_prefetch")
    if isinstance(pf, dict):
        _apply_tool_prefetch(messages, pf)

    merged_tools = _merge_tools(body.get("tools"))
    routed_category: str | None = None
    cats = classify_user_tool_categories(last_user_text(messages))
    cats = cats | extra_cats_body | extra_cats_hdr
    merged_tools = filter_merged_tools_by_categories(merged_tools, cats)
    if tool_domain and not (config.AGENT_ROUTER_STRICT_DEFAULT and not cats):
        merged_tools = filter_merged_tools_by_domain(merged_tools, tool_domain)
        non_intro = sum(
            1
            for t in merged_tools
            if (n := _tool_spec_name(t)) is not None and n not in TOOL_INTROSPECTION
        )
        if non_intro == 0:
            logger.warning(
                "tool domain filter %r removed all non-introspection tools; ignoring domain filter",
                tool_domain,
            )
            merged_tools = filter_merged_tools_by_categories(
                _merge_tools(body.get("tools")), cats
            )
    elif tool_domain and config.AGENT_ROUTER_STRICT_DEFAULT and not cats:
        logger.info(
            "skipping tool domain filter %r (AGENT_ROUTER_STRICT_DEFAULT with no categories)",
            tool_domain,
        )
    if cats:
        routed_category = (
            next(iter(cats)) if len(cats) == 1 else "+".join(sorted(cats))
        )
    elif config.AGENT_ROUTER_STRICT_DEFAULT:
        routed_category = "minimal"
    else:
        routed_category = "full"

    # Stufenweise Erkundung: tools[] immer nur Katalog — volles Schema nur via get_tool_help-Antwort.
    tools_for_request = _tools_for_chat_request(merged_tools)
    if config.AGENT_TOOLS_DENYLIST:
        deny = config.AGENT_TOOLS_DENYLIST
        tools_for_request = [
            t
            for t in tools_for_request
            if (n := _tool_spec_name(t)) is None or n not in deny
        ]

    if tools_for_request:
        names = [n for t in tools_for_request if (n := _tool_spec_name(t))]
        logger.info(
            "forwarding %d tools in chat request (model=%s, category=%s): %s",
            len(names),
            model,
            routed_category or "full",
            names,
        )
    _log_tools_request_estimate("chat_completions", tools_for_request)
    options = {
        k: v
        for k, v in body.items()
        if k not in ("messages", "model", "tools", "stream", *_BODY_KEYS_STRIP_FROM_OLLAMA)
    }

    url = f"{config.OLLAMA_BASE_URL}/v1/chat/completions"
    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=600.0) as client:
        for round_i in range(config.MAX_TOOL_ROUNDS):
            tools_for_round = list(tools_for_request)
            allowed_names = _names_from_tool_list(tools_for_round)

            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
                **options,
            }
            if tools_for_round:
                payload["tools"] = tools_for_round

            resp = await client.post(url, json=payload, headers=headers)
            if resp.is_error:
                err_body = (resp.text or "")[:4000]
                logger.error(
                    "Ollama chat/completions failed: status=%s model=%s body=%s",
                    resp.status_code,
                    model,
                    err_body or "(empty)",
                )
            resp.raise_for_status()
            data = resp.json()

            choice0 = (data.get("choices") or [{}])[0]
            raw_msg = choice0.get("message")
            if not isinstance(raw_msg, dict):
                raw_msg = {}
            msg = dict(raw_msg)
            raw_tc = msg.get("tool_calls")
            had_native_tool_calls = isinstance(raw_tc, list) and len(raw_tc) > 0
            tool_calls = raw_tc if had_native_tool_calls else None
            if not tool_calls:
                tool_calls = _synthetic_tool_calls_from_message(
                    msg, choice0, allowed_tool_names=allowed_names
                )
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                    choice0["message"] = msg

            _log_ollama_round(
                round_i=round_i,
                model=model,
                messages=messages,
                tools_for_round=tools_for_round,
                msg=msg,
                choice0=choice0 if isinstance(choice0, dict) else {},
                tool_calls=tool_calls if isinstance(tool_calls, list) else None,
                had_native_tool_calls=had_native_tool_calls,
            )

            if not tool_calls:
                return data

            # Append assistant message (includes tool_calls, and content if any)
            messages.append(msg)

            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                args = _parse_tool_arguments(fn.get("arguments"))
                tool_call_id = tc.get("id") or ""
                logger.info("tool round %s: %s(%s)", round_i + 1, name, args)
                result = run_tool(name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result,
                    }
                )
                recovery = _http_error_recovery_hint(name, result)
                if recovery:
                    messages.append({"role": "system", "content": recovery})

        logger.warning(
            "max tool rounds (%s) exceeded ctx_msgs=%d ctx_text_chars~=%d",
            config.MAX_TOOL_ROUNDS,
            len(messages),
            _approx_text_chars_in_messages(messages),
        )
        return data
