"""Introspection: list registered tools and fetch one tool's schema from the live registry (Chat Completions ``tools[]`` shape)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from app import config
from app.registry import get_registry
from app.tool_name_hints import suggest_tool_names

__version__ = "1.4.1"
TOOL_ID = "tool_help"


def list_available_tools(arguments: dict[str, Any]) -> str:
    """Return every tool name and short TOOL_DESCRIPTION only (no parameter schemas — use get_tool_help)."""
    _ = arguments
    reg = get_registry()
    tools_out: list[dict[str, Any]] = []
    for spec in reg.chat_tool_specs:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        tools_out.append(
            {
                "name": name,
                "TOOL_DESCRIPTION": (fn.get("TOOL_DESCRIPTION") or "").strip(),
            }
        )
    return json.dumps(
        {
            "ok": True,
            "count": len(tools_out),
            "tools": tools_out,
            "hint": (
                "Parameters omitted. For fewer tokens: list_tool_categories → list_tools_in_category(category) "
                "→ get_tool_help(tool_name) for full JSON Schema, then invoke."
            ),
        },
        ensure_ascii=False,
    )


def list_tool_categories(arguments: dict[str, Any]) -> str:
    """Router categories: id, human TOOL_LABEL, short TOOL_DESCRIPTION, tool count (no tool schemas)."""
    _ = arguments
    reg = get_registry()
    cats = reg.list_router_categories_catalog()
    return json.dumps(
        {
            "ok": True,
            "count": len(cats),
            "categories": cats,
            "hint": (
                "Pick a category id, then call list_tools_in_category with that id for name + TOOL_DESCRIPTION only. "
                "Call get_tool_help(tool_name) before invoking a tool."
            ),
        },
        ensure_ascii=False,
    )


def list_tools_in_category(arguments: dict[str, Any]) -> str:
    """Tools in one router category: name + TOOL_DESCRIPTION only (no parameters)."""
    raw = arguments.get("category")
    category = str(raw).strip().lower() if raw is not None else ""
    if not category:
        return json.dumps({"ok": False, "error": "category is required (id from list_tool_categories)"})
    reg = get_registry()
    rows = reg.list_router_category_tools_lite(category)
    if not rows:
        return json.dumps(
            {
                "ok": False,
                "error": f"unknown or empty category: {category!r}",
                "hint": "Use list_tool_categories for valid ids.",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "ok": True,
            "category": category,
            "count": len(rows),
            "tools": rows,
            "hint": "Call get_tool_help(tool_name) for the full parameter schema before invoking.",
        },
        ensure_ascii=False,
    )


def _module_readable_via_read_tool(module_source: str) -> bool:
    """True if ``module_source`` is ``file:...`` under ``AGENT_TOOLS_EXTRA_DIR`` (same rule as read_tool)."""
    raw_ex = (config.TOOLS_EXTRA_DIR or "").strip()
    if not raw_ex or not module_source.startswith("file:"):
        return False
    try:
        mod_path = Path(module_source[5:]).resolve()
        extra = Path(raw_ex).expanduser().resolve()
        mod_path.relative_to(extra)
        return True
    except (ValueError, OSError):
        return False


def get_tool_help(arguments: dict[str, Any]) -> str:
    """Return full TOOL_DESCRIPTION + parameter schema for a single tool."""
    name = (arguments.get("tool_name") or "").strip()
    if not name:
        return json.dumps({"ok": False, "error": "tool_name is required"})
    reg = get_registry()
    for spec in reg.chat_tool_specs:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        if fn.get("name") != name:
            continue
        meta = reg.meta_entry_for_tool_name(name)
        module_source: str | None = None
        if meta:
            src = meta.get("source")
            module_source = str(src) if isinstance(src, str) and src.strip() else None
        readable = _module_readable_via_read_tool(module_source or "")
        read_tool_hint: str
        if not module_source:
            read_tool_hint = "No module path in registry meta for this name (unexpected)."
        elif readable:
            read_tool_hint = (
                "module_source is under AGENT_TOOLS_EXTRA_DIR: read_tool with registered_tool_name or filename works."
            )
        else:
            read_tool_hint = (
                "module_source is the on-disk path of the defining .py (shipped image or other root). "
                "read_tool only reads files under AGENT_TOOLS_EXTRA_DIR — do not pass this path to read_tool; "
                "invoke this tool using parameters above."
            )
        return json.dumps(
            {
                "ok": True,
                "name": name,
                "TOOL_DESCRIPTION": fn.get("TOOL_DESCRIPTION") or "",
                "parameters": fn.get("parameters") or {},
                "module_source": module_source,
                "readable_via_read_tool": readable,
                "read_tool_hint": read_tool_hint,
                "how_to_use": (
                    "The model calls this tool with a JSON object matching "
                    "`parameters.properties`; required keys are in `parameters.required`."
                ),
            },
            ensure_ascii=False,
        )
    suggestions = suggest_tool_names(reg, name)
    return json.dumps(
        {
            "ok": False,
            "error": f"unknown tool: {name}",
            "hint": (
                "Use exact names from list_tools_in_category or list_available_tools. "
                "There is no tool named openai_function or get_tool_result — "
                "call the real tool (e.g. fishing_index) with tool_calls, or list first."
            ),
            "suggestions": suggestions,
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "list_available_tools": list_available_tools,
    "list_tool_categories": list_tool_categories,
    "list_tools_in_category": list_tools_in_category,
    "get_tool_help": get_tool_help,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_available_tools",
            "TOOL_DESCRIPTION": (
                "Lists all tools: name and short TOOL_DESCRIPTION only (no parameter schemas). "
                "Prefer list_tool_categories → list_tools_in_category when exploring by domain; "
                "use get_tool_help(tool_name) for full schema before calling a tool."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tool_categories",
            "TOOL_DESCRIPTION": (
                "Lists router tool categories: id, short TOOL_LABEL, TOOL_DESCRIPTION, and how many tools each has. "
                "No per-tool schemas. Next step: list_tools_in_category(category=id)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tools_in_category",
            "TOOL_DESCRIPTION": (
                "Lists tools in one category: each tool's name and short TOOL_DESCRIPTION only (no JSON parameter schema). "
                "Use get_tool_help(tool_name) for the full schema of the tool you intend to call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Category id from list_tool_categories (e.g. gmail, tool_factory)",
                    },
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tool_help",
            "TOOL_DESCRIPTION": (
                "Returns full help for one tool: TOOL_DESCRIPTION and parameter schema. "
                "If the name is wrong, the response includes suggestions (e.g. openweather_retrieve → openweather_current). "
                "Call this for exactly one tool before invoking it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Exact tool name from list_tools_in_category or list_available_tools",
                    },
                },
                "required": ["tool_name"],
            },
        },
    },
]
