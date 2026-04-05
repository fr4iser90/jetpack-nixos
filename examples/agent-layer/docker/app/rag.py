"""RAG: chunking, Ollama embeddings, ingest + search (Postgres pgvector)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

from . import config
from . import db
from . import identity

logger = logging.getLogger(__name__)


def _expected_dim() -> int:
    return int(config.AGENT_RAG_EMBEDDING_DIM)


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    chunk_size = max(200, int(chunk_size))
    overlap = max(0, min(int(overlap), chunk_size - 1))
    step = chunk_size - overlap
    out: list[str] = []
    i = 0
    while i < len(t):
        out.append(t[i : i + chunk_size])
        i += step
    return [c for c in out if c.strip()]


def ollama_embed_one(text: str) -> list[float]:
    """Single string → one embedding (Ollama ``/api/embeddings``)."""
    url = f"{config.OLLAMA_BASE_URL}/api/embeddings"
    body = {"model": config.AGENT_RAG_OLLAMA_MODEL, "input": text}
    with httpx.Client(timeout=float(config.AGENT_RAG_EMBED_TIMEOUT)) as client:
        r = client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
    emb = data.get("embedding")
    if not isinstance(emb, list):
        raise ValueError("Ollama embeddings response missing embedding[]")
    vec = [float(x) for x in emb]
    want = _expected_dim()
    if len(vec) != want:
        raise ValueError(
            f"embedding dim {len(vec)} != AGENT_RAG_EMBEDDING_DIM {want} "
            f"(model {config.AGENT_RAG_OLLAMA_MODEL!r}; DB column is vector(768))"
        )
    return vec


def ingest_for_user(
    tenant_id: int,
    user_id: int,
    domain: str,
    title: str,
    text: str,
    source_uri: str | None = None,
) -> dict[str, Any]:
    if not config.AGENT_RAG_ENABLED:
        raise ValueError("RAG is disabled (AGENT_RAG_ENABLED=false)")
    raw = (text or "").strip()
    if not raw:
        raise ValueError("text is required")
    chunks = chunk_text(
        raw, config.AGENT_RAG_CHUNK_SIZE, config.AGENT_RAG_CHUNK_OVERLAP
    )
    if not chunks:
        raise ValueError("no chunks after splitting")
    indexed: list[tuple[int, str, list[float]]] = []
    for i, ch in enumerate(chunks):
        emb = ollama_embed_one(ch)
        indexed.append((i, ch, emb))
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    doc_id, n = db.rag_document_and_chunks_insert(
        tenant_id,
        user_id,
        domain,
        title,
        source_uri,
        sha,
        indexed,
    )
    return {
        "ok": True,
        "document_id": doc_id,
        "chunk_count": n,
        "domain": (domain or "").strip(),
        "title": (title or "").strip(),
    }


def search_for_identity(
    query: str,
    domain: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if not config.AGENT_RAG_ENABLED:
        return []
    q = (query or "").strip()
    if not q:
        return []
    emb = ollama_embed_one(q)
    tenant_id, user_id = identity.get_identity()
    lim = limit if limit is not None else config.AGENT_RAG_TOP_K
    return db.rag_vector_search(tenant_id, user_id, emb, domain, int(lim))
