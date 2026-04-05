"""Tool list shaping: category filter from registry metadata (``TOOL_DOMAIN``, triggers, …)."""

from __future__ import annotations

import logging
import os
from typing import Any

from . import config
from .registry import get_registry

logger = logging.getLogger(__name__)

# Cross-cutting tools included when ``X-Agent-Tool-Domain`` / ``TOOL_DOMAIN`` is set.
TOOL_DOMAIN_SHARED: str = "shared"

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
    """All categories whose TOOL_TRIGGERS match ``text`` (union filter + multi-intent)."""
    return get_registry().classify_tool_router_categories(text)


def filter_merged_tools_by_category(tools: list[Any], category: str) -> list[Any]:
    """Keep tools registered under this category plus introspection tools."""
    return filter_merged_tools_by_categories(tools, frozenset({category.strip().lower()}))


def _minimal_router_allow_names() -> frozenset[str]:
    """Tool names allowed when router falls back to the small default set (strict mode)."""
    raw = (os.environ.get("AGENT_ROUTER_MINIMAL_TOOLS") or "").strip()
    if raw:
        return frozenset(x.strip().lower() for x in raw.split(",") if x.strip())
    return TOOL_INTROSPECTION


def filter_merged_tools_router_minimal(tools: list[Any]) -> list[Any]:
    """Keep only ``AGENT_ROUTER_MINIMAL_TOOLS`` (or built-in introspection quartet)."""
    allow = _minimal_router_allow_names()
    out: list[Any] = []
    for spec in tools:
        n = _tool_name(spec)
        if not n:
            out.append(spec)
            continue
        if n.strip().lower() in allow:
            out.append(spec)
    return out


def filter_merged_tools_by_domain(tools: list[Any], domain: str | None) -> list[Any]:
    """
    Keep tools whose module ``tools_meta`` declares ``domain`` equal to the requested id,
    or ``domain`` == ``shared`` (cross-cutting). Always keeps entries without a ``function.name``.
    """
    raw = (domain or "").strip().lower()
    if not raw:
        return list(tools)
    reg = get_registry()
    allow: set[str] = set(TOOL_INTROSPECTION)
    for spec in reg.chat_tool_specs:
        n = _tool_name(spec)
        if not n:
            continue
        meta = reg.meta_entry_for_tool_name(n)
        if not meta:
            continue
        dom = (meta.get("domain") or "").strip().lower()
        if dom == raw or dom == TOOL_DOMAIN_SHARED:
            allow.add(n)
    out: list[Any] = []
    for spec in tools:
        n = _tool_name(spec)
        if not n:
            out.append(spec)
            continue
        if n in allow:
            out.append(spec)
    return out


def filter_merged_tools_by_categories(
    tools: list[Any], categories: frozenset[str]
) -> list[Any]:
    """Keep tools in any of ``categories`` plus introspection (list/get help, category browse)."""
    if not categories:
        if config.AGENT_ROUTER_STRICT_DEFAULT:
            return filter_merged_tools_router_minimal(tools)
        return list(tools)
    reg = get_registry()
    allow = set(TOOL_INTROSPECTION)
    for c in categories:
        allow |= set(reg.router_tool_names_for_category(c))
    if len(allow) <= len(TOOL_INTROSPECTION):
        logger.warning(
            "unknown or empty router categories %r; %s",
            categories,
            "using minimal toolset" if config.AGENT_ROUTER_STRICT_DEFAULT else "not filtering (legacy)",
        )
        if config.AGENT_ROUTER_STRICT_DEFAULT:
            return filter_merged_tools_router_minimal(tools)
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
