"""Per-user notes / second brain in PostgreSQL (full-text + ILIKE). Scoped like todos."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import db

__version__ = "1.0.0"
TOOL_ID = "kb"
TOOL_DOMAIN = "kb"
TOOL_LABEL = "Knowledge base"
TOOL_DESCRIPTION = (
    "Per-user notes in PostgreSQL: append, full-text search, and read (same scope as todos)."
)
TOOL_TRIGGERS = ("knowledge base", "second brain", "my notes", "notebook")


def kb_append_note(arguments: dict[str, Any]) -> str:
    title = (arguments.get("title") or "").strip()
    body = (arguments.get("body") or "").strip()
    if not body:
        return json.dumps({"ok": False, "error": "body is required"})
    try:
        nid = db.kb_note_append(title, body)
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "id": nid, "title": title}, ensure_ascii=False)


def kb_search_notes(arguments: dict[str, Any]) -> str:
    q = (arguments.get("query") or "").strip()
    if not q:
        return json.dumps({"ok": False, "error": "query is required"})
    try:
        limit = int(arguments.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    rows = db.kb_note_search(q, limit)
    return json.dumps(
        {"ok": True, "notes": rows, "count": len(rows)}, ensure_ascii=False
    )


def kb_read_note(arguments: dict[str, Any]) -> str:
    try:
        nid = int(arguments.get("note_id"))
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "note_id must be an integer"})
    row = db.kb_note_get(nid)
    if not row:
        return json.dumps({"ok": False, "error": "note not found", "note_id": nid})
    return json.dumps({"ok": True, "note": row}, ensure_ascii=False)


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "kb_append_note": kb_append_note,
    "kb_search_notes": kb_search_notes,
    "kb_read_note": kb_read_note,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "kb_append_note",
            "TOOL_DESCRIPTION": (
                "Save a personal note for the current user (Postgres, same identity as todos). "
                "Use for facts, project context, or a lightweight second brain."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Short title (optional, may be empty).",
                    },
                    "body": {"type": "string", "TOOL_DESCRIPTION": "Note text (required)."},
                },
                "required": ["body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_search_notes",
            "TOOL_DESCRIPTION": (
                "Search this user's notes by keywords (full-text + substring). "
                "Returns excerpts; use kb_read_note for full body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max rows 1–50 (default 20).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_read_note",
            "TOOL_DESCRIPTION": "Load one note by id (from kb_search_notes); body may be truncated if very long.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "integer"},
                },
                "required": ["note_id"],
            },
        },
    },
]
