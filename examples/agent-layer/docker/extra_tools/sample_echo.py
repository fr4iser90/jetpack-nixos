# Copy into AGENT_TOOLS_EXTRA_DIR (flat or nested subfolders; registry scans recursively).

from __future__ import annotations

import json
from typing import Any, Callable

__version__ = "0.1.0"
TOOL_ID = "echo"


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
            "TOOL_DESCRIPTION": "Returns the given text unchanged (demo extra tool).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "TOOL_DESCRIPTION": "Text to echo"},
                },
                "required": ["text"],
            },
        },
    },
]
