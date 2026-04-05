"""Apply a substring patch to an existing ``.py`` under AGENT_TOOLS_EXTRA_DIR (then validate + reload)."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent_tools.core.tool_factory._tool_factory_common import (
    backup_extra_tool_before_write,
    coalesce_tool_file_target,
    digest_reload_response,
    extra_root_or_error,
    reject_update_tool_confused_arguments,
    tool_write_extra_for_digest,
    validate_module_text,
)

__version__ = "1.4.0"
TOOL_ID = "update_tool"
TOOL_DOMAIN = "tool_factory"
TOOL_TRIGGERS = ()


def update_tool(arguments: dict[str, Any]) -> str:
    root, err = extra_root_or_error()
    if err:
        return err
    assert root is not None
    confused = reject_update_tool_confused_arguments(arguments)
    if confused:
        return confused
    fn, ferr = coalesce_tool_file_target(arguments, extra_root=root)
    if ferr:
        return ferr
    assert fn is not None
    old = arguments.get("old_string")
    if old is None:
        return json.dumps(
            {
                "ok": False,
                "error": "old_string is required (exact substring from read_tool output)",
                "hint": (
                    "update_tool is a text patch, not codegen. Use create_tool with tool_name/TOOL_DESCRIPTION to regenerate, "
                    "or replace_tool with full source. Optional: read_tool with registered_tool_name first."
                ),
            },
            ensure_ascii=False,
        )
    old_s = str(old)
    if old_s == "":
        return json.dumps({"ok": False, "error": "old_string cannot be empty"}, ensure_ascii=False)
    new = arguments.get("new_string")
    if new is None:
        new = ""
    new_s = str(new)

    dest = root / fn
    if not dest.is_file():
        return json.dumps(
            {"ok": False, "error": f"file does not exist: {fn}; use create_tool to add a new file"},
            ensure_ascii=False,
        )
    try:
        text = dest.read_text(encoding="utf-8")
    except OSError as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    count = text.count(old_s)
    if count == 0:
        return json.dumps({"ok": False, "error": "old_string not found", "filename": fn}, ensure_ascii=False)
    try:
        replace_all = bool(arguments.get("replace_all", False))
    except Exception:
        replace_all = False
    if not replace_all and count != 1:
        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"old_string matches {count} times; set replace_all true to replace all, "
                    "or make old_string unique (include more surrounding context)"
                ),
                "matches": count,
            },
            ensure_ascii=False,
        )
    if replace_all:
        updated = text.replace(old_s, new_s)
        replaced = count
    else:
        updated = text.replace(old_s, new_s, 1)
        replaced = 1

    val_err = validate_module_text(updated, fn, codegen=False)
    if val_err:
        return json.dumps(
            {
                "ok": False,
                "error": val_err,
                "hint": "File not written. Fix old_string/new_string or use read_tool then replace_tool with full source.",
            },
            ensure_ascii=False,
        )

    backup_path = backup_extra_tool_before_write(dest)
    try:
        dest.write_text(updated, encoding="utf-8", newline="\n")
    except OSError as e:
        return json.dumps({"ok": False, "error": f"write failed: {e}"}, ensure_ascii=False)

    body = json.loads(
        digest_reload_response(fn, dest, extra=tool_write_extra_for_digest(backup_path))
    )
    body["replacements"] = replaced
    return json.dumps(body, ensure_ascii=False)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "update_tool": update_tool,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_tool",
            "TOOL_DESCRIPTION": (
                "Patch a dynamic tool module under AGENT_TOOLS_EXTRA_DIR: old_string → new_string (not codegen). "
                "Use filename **or** registered_tool_name / tool_name / name (e.g. fishing_index). "
                "Do NOT pass overwrite/TOOL_DESCRIPTION/source here — those belong on create_tool or replace_tool. "
                "Unless replace_all is true, old_string must match exactly once. "
                "Flow: read_tool (same identifier) → update_tool. Full file: replace_tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "TOOL_DESCRIPTION": "Basename e.g. fishing_index.py"},
                    "registered_tool_name": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Registered tool function name if file is under AGENT_TOOLS_EXTRA_DIR (alternative to filename)",
                    },
                    "tool_name": {"type": "string", "TOOL_DESCRIPTION": "Alias for registered_tool_name"},
                    "name": {"type": "string", "TOOL_DESCRIPTION": "Alias for registered_tool_name"},
                    "old_string": {"type": "string", "TOOL_DESCRIPTION": "Exact substring to replace (use enough context to be unique)"},
                    "new_string": {"type": "string", "TOOL_DESCRIPTION": "Replacement text (may be empty to delete old_string)"},
                    "replace_all": {
                        "type": "boolean",
                        "TOOL_DESCRIPTION": "If true, replace every occurrence of old_string",
                    },
                },
                "required": ["old_string"],
            },
        },
    },
]
