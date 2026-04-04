"""Tool list shaping: category filter from registry metadata (``AGENT_TOOL_ROUTER_*`` on modules)."""

from __future__ import annotations

import logging
from typing import Any

from .registry import get_registry

logger = logging.getLogger(__name__)

TOOL_INTROSPECTION: frozenset[str] = frozenset(
    {
        "list_available_tools",
        "get_tool_help",
        "list_tool_categories",
        "list_tools_in_category",
    }
)


def _tool_name(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    fn = entry.get("function")
    if isinstance(fn, dict):
        n = fn.get("name")
        return str(n) if n else None
    return None


def last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        c = msg.get("content")
        if isinstance(c, str) and c.strip():
            return c
        if isinstance(c, list):
            parts: list[str] = []
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                    parts.append(p["text"])
            if parts:
                return "\n".join(parts)
    return ""


def classify_user_tool_category(text: str) -> str | None:
    """First matching category in router order (legacy). Prefer ``classify_user_tool_categories``."""
    return get_registry().classify_tool_router_category(text)


def classify_user_tool_categories(text: str) -> frozenset[str]:
    """All categories whose triggers match ``text`` (union filter + multi-intent)."""
    return get_registry().classify_tool_router_categories(text)


def filter_merged_tools_by_category(tools: list[Any], category: str) -> list[Any]:
    """Keep tools registered under this category plus introspection tools."""
    return filter_merged_tools_by_categories(tools, frozenset({category.strip().lower()}))


def filter_merged_tools_by_categories(
    tools: list[Any], categories: frozenset[str]
) -> list[Any]:
    """Keep tools in any of ``categories`` plus introspection (list/get help, category browse)."""
    if not categories:
        return list(tools)
    reg = get_registry()
    allow = set(TOOL_INTROSPECTION)
    for c in categories:
        allow |= set(reg.router_tool_names_for_category(c))
    if len(allow) <= len(TOOL_INTROSPECTION):
        logger.warning("unknown or empty router categories %r; not filtering", categories)
        return list(tools)
    out: list[Any] = []
    for spec in tools:
        n = _tool_name(spec)
        if not n:
            out.append(spec)
            continue
        if n in allow:
            out.append(spec)
    return out
