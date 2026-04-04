"""Dispatch tool calls by name (chat loop, tests, and :mod:`app.plugin_invoke`)."""

from __future__ import annotations

import json
import os
from contextvars import ContextVar, Token

from .registry import get_registry

__all__ = ["run_tool"]

_chain_depth: ContextVar[int] = ContextVar("agent_tool_chain_depth", default=0)


def _max_chain_depth() -> int:
    raw = (os.environ.get("AGENT_TOOL_CHAIN_MAX_DEPTH") or "").strip()
    if not raw:
        return 24
    try:
        n = int(raw)
    except ValueError:
        return 24
    return max(1, min(256, n))


def run_tool(name: str, arguments: dict) -> str:
    """
    Run a registered handler. Nested calls (plugin → other tool) increment a context
    depth counter; exceeding :envvar:`AGENT_TOOL_CHAIN_MAX_DEPTH` returns JSON error.
    """
    depth = _chain_depth.get()
    limit = _max_chain_depth()
    if depth >= limit:
        return json.dumps(
            {
                "ok": False,
                "error": f"tool chain depth exceeded ({limit}); avoid recursive tool calls",
            },
            ensure_ascii=False,
        )
    token: Token[int] | None = None
    try:
        token = _chain_depth.set(depth + 1)
        return get_registry().run_tool(name, arguments)
    finally:
        if token is not None:
            _chain_depth.reset(token)
