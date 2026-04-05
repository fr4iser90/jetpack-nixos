"""List ``*.py`` basenames in AGENT_TOOLS_EXTRA_DIR (writable tool modules, one level)."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent_tools.core.tool_factory._tool_factory_common import extra_root_or_error

__version__ = "1.1.0"
TOOL_ID = "list_tools"
TOOL_DOMAIN = "tool_factory"
TOOL_TRIGGERS = ()


def list_tools(arguments: dict[str, Any]) -> str:
    _ = arguments
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    names = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix == ".py")
    return json.dumps(
        {
            "ok": True,
            "directory": str(root),
            "files": names,
            "hint": (
                "Basenames in AGENT_TOOLS_EXTRA_DIR only (extra/dynamic .py). "
                "Built-in tools from the image (openweather_*, github_*, etc.) do not appear here. "
                "read_tool/update_tool/replace_tool apply only to files in this list. "
                "For all registered tool function names, use list_available_tools."
            ),
        },
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "list_tools": list_tools,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_tools",
            "TOOL_DESCRIPTION": (
                "List .py basenames in AGENT_TOOLS_EXTRA_DIR (writable tool-module directory, top level only). "
                "Not the same as list_available_tools (that lists all registered tool names)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]
