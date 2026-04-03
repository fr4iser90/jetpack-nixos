# Copy into a directory mounted as AGENT_PLUGINS_EXTRA_DIR (see compose.yaml).
# After adding or editing files: POST /v1/admin/reload-plugins (with AGENT_API_KEY if set).

from __future__ import annotations

import json
from typing import Any, Callable

__version__ = "0.1.0"
PLUGIN_ID = "echo"


def echo_text(arguments: dict[str, Any]) -> str:
    text = arguments.get("text")
    return json.dumps({"ok": True, "echo": text})


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "echo_text": echo_text,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "echo_text",
            "description": "Returns the given text unchanged (demo extra plugin).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to echo"},
                },
                "required": ["text"],
            },
        },
    },
]
