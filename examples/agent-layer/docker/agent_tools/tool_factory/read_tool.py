"""Read full source of one ``.py`` tool module under AGENT_TOOLS_EXTRA_DIR."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import config

from agent_tools.tool_factory._tool_factory_common import coalesce_tool_file_target, extra_root_or_error

__version__ = "1.3.0"
TOOL_ID = "read_tool"
AGENT_TOOL_ROUTER_CATEGORY = "tool_factory"
AGENT_TOOL_ROUTER_TRIGGERS = ()


def read_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    fn, ferr = coalesce_tool_file_target(arguments, extra_root=root)
    if ferr:
        return ferr
    assert fn is not None
    dest = root / fn
    if not dest.is_file():
        return json.dumps(
            {
                "ok": False,
                "error": f"not found: {fn}",
                "hint": (
                    "read_tool only reads basenames under AGENT_TOOLS_EXTRA_DIR (extra / dynamic plugins). "
                    "Built-in tools (e.g. openweather_current) are loaded from the image's agent_tools/ tree — "
                    "there is no .py path for them here. Use get_tool_help(\"tool_name\") for the schema; "
                    "list_tools lists only files in the extra directory."
                ),
            },
            ensure_ascii=False,
        )
    try:
        text = dest.read_text(encoding="utf-8")
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    if len(text.encode("utf-8")) > config.CREATE_TOOL_MAX_BYTES:
        return json.dumps(
            {
                "ok": False,
                "error": f"file larger than AGENT_CREATE_TOOL_MAX_BYTES ({config.CREATE_TOOL_MAX_BYTES})",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"ok": True, "filename": fn, "source": text, "byte_length": len(text.encode("utf-8"))},
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "read_tool": read_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_tool",
            "description": (
                "Return full UTF-8 source of one .py file located **only** under AGENT_TOOLS_EXTRA_DIR "
                "(the writable extra-tools mount, same as create_tool/update_tool). "
                "**Do not** pass names of built-in image tools (e.g. openweather_current.py) — those modules are "
                "not in that directory; use get_tool_help(\"openweather_current\") for schema, not read_tool. "
                "Use filename **or** registered_tool_name when the tool is registered **from** the extra dir "
                "(e.g. biting_index). Call list_tools first to see valid basenames."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Basename e.g. fishing_index.py"},
                    "registered_tool_name": {
                        "type": "string",
                        "description": "Exact registered tool function name (e.g. fishing_index) if the module lives under AGENT_TOOLS_EXTRA_DIR",
                    },
                    "tool_name": {"type": "string", "description": "Alias for registered_tool_name"},
                    "name": {"type": "string", "description": "Alias for registered_tool_name"},
                },
            },
        },
    },
]
