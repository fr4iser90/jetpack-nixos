"""
Call other **registered** tools from inside a ``TOOLS``/``HANDLERS`` plugin (including
files under ``AGENT_TOOLS_EXTRA_DIR``). Same execution path as the chat tool loop:
registry dispatch + ``tool_invocations`` logging.

Example (extra plugin)::

    import json
    from app.plugin_invoke import invoke_registered_tool

    def fishing_index(arguments: dict) -> str:
        raw = invoke_registered_tool(
            "openweather_forecast",
            {"location": arguments.get("location") or "", "max_slots": 16},
        )
        data = json.loads(raw)
        if not data.get("ok"):
            return raw
        # ... compute heuristic from data[\"forecast\"] ...
        return json.dumps({"ok": True, "score": 7.2})

Use the **registered tool function name** (e.g. ``openweather_forecast``), not the file name.
Avoid recursion (tool A calling tool A) and very deep chains; see
``AGENT_TOOL_CHAIN_MAX_DEPTH`` in ``.env.example``.
"""

from __future__ import annotations

from typing import Any

from .tools import run_tool

__all__ = ["invoke_registered_tool"]


def invoke_registered_tool(name: str, arguments: dict[str, Any] | None = None) -> str:
    """Run another tool by its registered name; returns the handler's JSON string."""
    return run_tool(name, dict(arguments or {}))
