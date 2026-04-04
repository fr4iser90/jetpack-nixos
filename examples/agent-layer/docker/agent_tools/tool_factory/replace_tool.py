"""Replace an existing ``.py`` tool module under AGENT_TOOLS_EXTRA_DIR (full ``source``)."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent_tools.tool_factory._tool_factory_common import (
    backup_extra_tool_before_write,
    coalesce_tool_file_target,
    digest_reload_response,
    extra_root_or_error,
    reject_replace_tool_confused_arguments,
    tool_write_extra_for_digest,
    validate_module_text,
)

__version__ = "1.1.0"
TOOL_ID = "replace_tool"
AGENT_TOOL_ROUTER_CATEGORY = "tool_factory"
AGENT_TOOL_ROUTER_TRIGGERS = ()


def replace_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    confused = reject_replace_tool_confused_arguments(arguments)
    if confused:
        return confused
    fn, ferr = coalesce_tool_file_target(arguments, extra_root=root)
    if ferr:
        return ferr
    assert fn is not None
    source = arguments.get("source")
    if source is None or not str(source).strip():
        return json.dumps({"ok": False, "error": "source required (full module text)"}, ensure_ascii=False)
    text = str(source)
    val_err = validate_module_text(text, fn, codegen=False)
    if val_err:
        return json.dumps({"ok": False, "error": val_err}, ensure_ascii=False)
    dest = root / fn
    if not dest.is_file():
        return json.dumps(
            {"ok": False, "error": f"file does not exist: {fn}; use create_tool to add a new file"},
            ensure_ascii=False,
        )
    backup_path = backup_extra_tool_before_write(dest)
    try:
        dest.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)
    return digest_reload_response(fn, dest, extra=tool_write_extra_for_digest(backup_path))


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "replace_tool": replace_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "replace_tool",
            "description": (
                "Replace an entire .py tool module with new full source; compile + AST + registry shape check; reload. "
                "For small edits without rewriting the whole file, prefer update_tool (old_string → new_string)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "openai_tool_name": {"type": "string", "description": "Alternative to filename when the tool lives under AGENT_TOOLS_EXTRA_DIR"},
                    "tool_name": {"type": "string", "description": "Alias for openai_tool_name"},
                    "name": {"type": "string", "description": "Alias for openai_tool_name"},
                    "source": {"type": "string", "description": "Full replacement module text"},
                },
                "required": ["source"],
            },
        },
    },
]
