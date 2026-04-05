"""Wall-clock tool (no database)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

__version__ = "1.0.0"
TOOL_ID = "clock"
TOOL_DOMAIN = "clocks"
TOOL_LABEL = "Clocks"
TOOL_DESCRIPTION = "Current time and IANA timezone names (no database)."
TOOL_TRIGGERS = ("timezone", "utc", "what time", "clock", "zoneinfo")


def get_current_time(arguments: dict[str, Any]) -> str:
    tz_name = (arguments.get("timezone_name") or "UTC").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    return json.dumps(
        {
            "iso": now.isoformat(),
            "timezone": tz_name,
            "unix": time.time(),
        }
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "get_current_time": get_current_time,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "TOOL_DESCRIPTION": "Returns current time as ISO string. Optional IANA timezone, e.g. Europe/Berlin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone_name": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "IANA timezone name, default UTC",
                    },
                },
            },
        },
    },
]
