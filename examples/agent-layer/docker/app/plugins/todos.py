"""Todo tools backed by PostgreSQL."""

from __future__ import annotations

import json
from typing import Any, Callable

from .. import db

__version__ = "1.0.0"
PLUGIN_ID = "todos"


def create_todo(arguments: dict[str, Any]) -> str:
    title = (arguments.get("title") or "").strip()
    if not title:
        return json.dumps({"ok": False, "error": "title is empty"})
    tid = db.todo_create(title)
    return json.dumps({"ok": True, "id": tid, "title": title})


def list_todos(arguments: dict[str, Any]) -> str:
    _ = arguments
    items = db.todo_list(100)
    out = []
    for row in items:
        out.append(
            {
                "id": row["id"],
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
            }
        )
    return json.dumps({"ok": True, "todos": out})


def set_todo_status(arguments: dict[str, Any]) -> str:
    status = (arguments.get("status") or "").strip().lower()
    if status not in ("open", "done", "cancelled"):
        return json.dumps(
            {"ok": False, "error": "status must be open, done, or cancelled"}
        )
    try:
        tid = int(arguments.get("todo_id"))
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "invalid todo id"})
    if not db.todo_set_status(tid, status):
        return json.dumps({"ok": False, "error": "todo not found", "id": tid})
    return json.dumps({"ok": True, "id": tid, "status": status})


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "create_todo": create_todo,
    "list_todos": list_todos,
    "set_todo_status": set_todo_status,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": "Creates a todo item in the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short todo title"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "Lists todo items from the database (newest first, max 100).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_todo_status",
            "description": "Updates a todo's status by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "Todo id from list_todos",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "done", "cancelled"],
                    },
                },
                "required": ["todo_id", "status"],
            },
        },
    },
]
