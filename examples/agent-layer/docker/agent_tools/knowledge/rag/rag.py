"""Vector RAG over Postgres + pgvector (Ollama embeddings). Scoped per user like KB/todos."""

from __future__ import annotations

import json
from typing import Any, Callable

from app import config
from app import rag as rag_service

__version__ = "1.0.0"
TOOL_ID = "rag"
TOOL_DOMAIN = "rag"
TOOL_LABEL = "RAG"
TOOL_DESCRIPTION = (
    "Semantic search over ingested documents (pgvector + Ollama embeddings)."
)
TOOL_TRIGGERS = (
    "rag",
    "vector search",
    "semantic search",
    "embeddings",
    "knowledge base documents",
)


def rag_search(arguments: dict[str, Any]) -> str:
    if not config.AGENT_RAG_ENABLED:
        return json.dumps({"ok": False, "error": "RAG disabled (AGENT_RAG_ENABLED=false)"})
    q = (arguments.get("query") or "").strip()
    if not q:
        return json.dumps({"ok": False, "error": "query is required"})
    domain = arguments.get("domain")
    dom = domain.strip() if isinstance(domain, str) else None
    if dom == "":
        dom = None
    try:
        limit = int(arguments.get("limit") or config.AGENT_RAG_TOP_K)
    except (TypeError, ValueError):
        limit = config.AGENT_RAG_TOP_K
    try:
        rows = rag_service.search_for_identity(q, domain=dom, limit=limit)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps(
        {"ok": True, "hits": rows, "count": len(rows)},
        ensure_ascii=False,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "rag_search": rag_search,
}

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "TOOL_DESCRIPTION": (
                "Semantic search over documents previously ingested for this user (vector similarity). "
                "Use optional domain to restrict results. Ingest via POST /v1/admin/rag/ingest."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Natural-language query to embed and match.",
                    },
                    "domain": {
                        "type": "string",
                        "TOOL_DESCRIPTION": "Optional document domain filter (exact match; omit for all domains).",
                    },
                    "limit": {
                        "type": "integer",
                        "TOOL_DESCRIPTION": "Max hits 1–50 (default from AGENT_RAG_TOP_K).",
                    },
                },
                "required": ["query"],
            },
        },
    },
]
