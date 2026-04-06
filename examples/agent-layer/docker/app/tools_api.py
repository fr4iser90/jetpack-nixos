"""HTTP routes for tool schemas and tool registry admin (no per-tool hardcoding)."""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request

from . import config
from .auth import require_permission
from .registry import get_registry, reload_registry

logger = logging.getLogger(__name__)

router = APIRouter()


def _registered_function_name(spec: dict) -> str | None:
    fn = spec.get("function") if isinstance(spec, dict) else None
    if isinstance(fn, dict):
        n = fn.get("name")
        return str(n) if n else None
    return None


@router.get("/v1/tools")
async def list_tools():
    """Chat ``tools[]``-shaped specs plus registry metadata (every ``*.py`` under configured tool dirs)."""
    reg = get_registry()
    return {"tools": reg.chat_tool_specs, "tools_meta": reg.tools_meta}


@router.get("/v1/router/categories")
async def list_router_categories():
    """Router category ids (from each module's ``TOOL_DOMAIN``) for operator UIs and .env presets."""
    reg = get_registry()
    return {"categories": reg.list_router_categories_catalog()}


@router.get("/v1/admin/tools")
async def admin_list_tools():
    """Tool metadata only (id, version, source, tool names)."""
    reg = get_registry()
    return {"tools": reg.tools_meta}


@router.post("/v1/admin/reload-tools")
@require_permission("write", "tool")
async def admin_reload_tools(request: Request, user, scope: Literal["all", "extra"] = "all"):
    """
    Rescan all configured tool directories (``AGENT_TOOL_DIRS`` or defaults).
    Broken or conflicting tools are skipped with logs. ``scope`` is accepted for API
    compatibility; both values perform the same full rescan.
    """
    try:
        reg = reload_registry(scope=scope)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("reload-tools failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    names = [_registered_function_name(t) for t in reg.chat_tool_specs]
    return {
        "ok": True,
        "scope": scope,
        "tools": reg.tools_meta,
        "tool_count": len(reg.chat_tool_specs),
        "tool_names": [n for n in names if n],
    }


@router.post("/v1/admin/create-tool")
@require_permission("write", "tool")
async def admin_create_tool(request: Request, user):
    """
    Same JSON body as the chat tool ``create_tool`` (codegen without ``source``, or full module in ``source``).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object expected")

    from tools.agent.core.tool_factory.create_tool import create_tool as run_create_tool

    raw = run_create_tool(body)
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("create-tool returned non-JSON: %s", raw[:500])
        raise HTTPException(status_code=500, detail="create-tool returned invalid JSON") from None
    return out
