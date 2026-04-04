"""Fuzzy tool-name suggestions when models invent wrong registered tool function names."""

from __future__ import annotations

import difflib

from .registry import ToolRegistry

# Common hallucinations → real registered names (lowercase keys).
_TOOL_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "openweather_retrieve": ("openweather_current", "openweather_forecast"),
    "openweather_get": ("openweather_current", "openweather_forecast"),
    "openweather_fetch": ("openweather_current", "openweather_forecast"),
    "weather_get": ("openweather_current", "openweather_forecast"),
    "openai_function": ("list_available_tools", "get_tool_help"),
    "get_tool_result": ("list_available_tools",),
    "call_tool": ("list_available_tools", "get_tool_help"),
}


def _all_registered_function_names(reg: ToolRegistry) -> list[str]:
    out: list[str] = []
    for spec in reg.chat_tool_specs:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if isinstance(fn, dict):
            n = fn.get("name")
            if isinstance(n, str) and n.strip():
                out.append(n.strip())
    return out


def suggest_tool_names(reg: ToolRegistry, query: str, *, limit: int = 10) -> list[str]:
    """Return likely intended tool names for a wrong or partial hint."""
    q = (query or "").strip()
    if not q:
        return []
    ql = q.lower()
    names = _all_registered_function_names(reg)
    out: list[str] = []

    if ql in _TOOL_NAME_ALIASES:
        out.extend(_TOOL_NAME_ALIASES[ql])
    for alias, targets in _TOOL_NAME_ALIASES.items():
        if alias in ql or ql in alias:
            for t in targets:
                if t not in out:
                    out.append(t)

    for m in difflib.get_close_matches(q, names, n=8, cutoff=0.32):
        if m not in out:
            out.append(m)

    qls = ql.replace("_", "").replace("-", "")
    for n in names:
        nl = n.lower()
        nls = nl.replace("_", "").replace("-", "")
        if ql in nl or nl in ql or (qls and qls in nls):
            if n not in out:
                out.append(n)

    return out[:limit]
