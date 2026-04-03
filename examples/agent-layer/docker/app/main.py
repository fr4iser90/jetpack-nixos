"""OpenAI-compatible HTTP API: proxies to Ollama and executes local tools."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import config
from . import db
from .agent import chat_completion
from .registry import get_registry, reload_registry

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_pool()
    db.migrate()
    get_registry()
    yield
    db.close_pool()


app = FastAPI(title="agent-layer", version="0.4.0", lifespan=lifespan)

_cors_origins = [
    o.strip() for o in os.environ.get("AGENT_CORS_ORIGINS", "*").split(",") if o.strip()
]
_cors_credentials = "*" not in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def optional_api_key(request: Request, call_next):
    if not config.OPTIONAL_API_KEY:
        return await call_next(request)
    if request.url.path in ("/health", "/v1/models"):
        return await call_next(request)
    auth = request.headers.get("authorization") or ""
    token = auth.removeprefix("Bearer ").strip()
    if token != config.OPTIONAL_API_KEY:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)


@app.get("/health")
def health():
    try:
        with db.pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.commit()
    except Exception:
        logger.exception("database health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "down"},
        )
    return {"status": "ok", "database": "ok"}


@app.get("/v1/models")
async def models_proxy():
    """Passthrough so UIs can list Ollama models."""
    import httpx

    url = f"{config.OLLAMA_BASE_URL}/v1/models"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


def _completion_to_sse_lines(completion: dict[str, Any]) -> bytes:
    """Build OpenAI-style SSE body from a full chat.completion JSON (Open WebUI sends stream=true)."""
    cid = completion.get("id") or f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = completion.get("created")
    if not isinstance(created, int):
        created = int(time.time())
    model = completion.get("model") or ""
    choice0 = (completion.get("choices") or [{}])[0]
    msg = choice0.get("message") if isinstance(choice0.get("message"), dict) else {}
    content = msg.get("content") if isinstance(msg, dict) else None
    if content is None:
        content = ""
    elif not isinstance(content, str):
        content = str(content)
    finish = choice0.get("finish_reason") or "stop"
    base = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
    }
    lines: list[bytes] = []
    lines.append(
        (
            "data: "
            + json.dumps(
                {
                    **base,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": content},
                            "finish_reason": None,
                        }
                    ],
                },
                ensure_ascii=False,
            )
            + "\n\n"
        ).encode()
    )
    lines.append(
        (
            "data: "
            + json.dumps(
                {
                    **base,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": finish,
                        }
                    ],
                },
                ensure_ascii=False,
            )
            + "\n\n"
        ).encode()
    )
    lines.append(b"data: [DONE]\n\n")
    return b"".join(lines)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    want_stream = bool(body.get("stream"))
    work = dict(body)
    work["stream"] = False

    try:
        result = await chat_completion(work)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("chat completion failed")
        raise HTTPException(status_code=502, detail=str(e))

    if want_stream:
        return StreamingResponse(
            iter([_completion_to_sse_lines(result)]),
            media_type="text/event-stream",
        )

    return result


@app.get("/v1/tools")
async def list_tools():
    """Registered tool schemas (same list sent to the model when the client sends no tools)."""
    reg = get_registry()
    return {"tools": reg.openai_tools, "plugins": reg.plugins_meta}


@app.get("/v1/admin/plugins")
async def admin_list_plugins():
    """Plugin metadata only (id, version, source, tool names)."""
    reg = get_registry()
    return {"plugins": reg.plugins_meta}


@app.post("/v1/admin/reload-plugins")
async def admin_reload_plugins(
    scope: Literal["all", "extra"] = "all",
):
    """
    Rebuild the tool registry.

    - ``scope=all`` (default): reload ``app.plugins`` and ``AGENT_PLUGINS_EXTRA_DIR`` (full restart of plugin modules).
    - ``scope=extra``: only rescan ``AGENT_PLUGINS_EXTRA_DIR``; built-in plugins stay loaded (no ``importlib`` purge of ``app.plugins``).

    Optional: ``AGENT_PLUGINS_ALLOWED_SHA256`` — comma-separated SHA256 of allowed extra ``*.py`` files.

    If ``AGENT_API_KEY`` is set, send ``Authorization: Bearer <key>``.
    """
    if not config.OPTIONAL_API_KEY:
        logger.warning("reload-plugins called with AGENT_API_KEY unset — consider setting it if exposed")
    try:
        reg = reload_registry(scope=scope)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("reload-plugins failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "ok": True,
        "scope": scope,
        "plugins": reg.plugins_meta,
        "tool_count": len(reg.openai_tools),
    }
