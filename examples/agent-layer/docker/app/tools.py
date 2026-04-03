"""Shim: ``run_tool`` for callers that import from here."""

from __future__ import annotations

from .registry import get_registry

__all__ = ["run_tool"]


def run_tool(name: str, arguments: dict) -> str:
    return get_registry().run_tool(name, arguments)
