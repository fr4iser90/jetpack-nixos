"""Admin HTTP for RAG ingest (same identity headers as chat)."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import config
from .http_identity import resolve_user_tenant
from . import rag as rag_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v1/admin/rag/ingest")
async def admin_rag_ingest(request: Request):
    """
    Ingest plain text into pgvector-backed RAG for the resolved user/tenant
    (``AGENT_USER_SUB_HEADER`` / ``AGENT_TENANT_ID_HEADER``, same as chat).
    """
    if not config.AGENT_RAG_ENABLED:
        raise HTTPException(status_code=503, detail="RAG disabled (AGENT_RAG_ENABLED=false)")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object expected")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="text (non-empty string) is required")
    domain = body.get("domain") if isinstance(body.get("domain"), str) else ""
    title = body.get("title") if isinstance(body.get("title"), str) else ""
    source_uri = body.get("source_uri")
    su = source_uri if isinstance(source_uri, str) and source_uri.strip() else None

    user_id, tenant_id = resolve_user_tenant(request)
    try:
        out = rag_service.ingest_for_user(
            tenant_id, user_id, domain, title, text, su
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        logger.exception("RAG ingest Ollama error")
        raise HTTPException(
            status_code=502, detail=f"Ollama embeddings error: {e!s}"
        ) from e
    except httpx.RequestError as e:
        logger.exception("RAG ingest cannot reach Ollama")
        raise HTTPException(
            status_code=502, detail=f"Ollama unreachable: {e!s}"
        ) from e
    except Exception as e:
        logger.exception("RAG ingest failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return out
