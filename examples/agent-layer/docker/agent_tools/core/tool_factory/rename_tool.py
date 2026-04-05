"""Rename a ``*.py`` file under AGENT_TOOLS_EXTRA_DIR."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import tool_authoring

from agent_tools.core.tool_factory._tool_factory_common import (
    digest_reload_response,
    extra_root_or_error,
)

__version__ = "1.0.0"
TOOL_ID = "rename_tool"
TOOL_DOMAIN = "tool_factory"
TOOL_TRIGGERS = ()


def rename_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    old_fn, e1 = tool_authoring.sanitize_tool_filename(str(arguments.get("old_filename") or ""))
    new_fn, e2 = tool_authoring.sanitize_tool_filename(str(arguments.get("new_filename") or ""))
    if e1 or not old_fn:
        return json.dumps({"ok": False, "error": e1 or "old_filename required"}, ensure_ascii=False)
    if e2 or not new_fn:
        return json.dumps({"ok": False, "error": e2 or "new_filename required"}, ensure_ascii=False)
    old_p = root / old_fn
    new_p = root / new_fn
    if not old_p.is_file():
        return json.dumps({"ok": False, "error": f"not found: {old_fn}"}, ensure_ascii=False)
    overwrite = bool(arguments.get("overwrite", False))
    if new_p.exists() and not overwrite:
        return json.dumps(
            {"ok": False, "error": f"target exists: {new_fn}; pass overwrite:true to replace"},
            ensure_ascii=False,
        )
    try:
        if new_p.exists():
            new_p.unlink()
        old_p.rename(new_p)
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    return digest_reload_response(
        new_fn,
        new_p,
        extra={"renamed_from": old_fn},
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "rename_tool": rename_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "rename_tool",
            "TOOL_DESCRIPTION": "Rename a .py file under AGENT_TOOLS_EXTRA_DIR (basenames only); reload registry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_filename": {"type": "string"},
                    "new_filename": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["old_filename", "new_filename"],
            },
        },
    },
]
