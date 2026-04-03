"""HTTP API for per-user encrypted secrets (not for LLM chat — use curl / UI integration)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import config, db
from .http_identity import resolve_user_tenant

router = APIRouter(prefix="/v1/user/secrets", tags=["user-secrets"])

_SERVICE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


def _require_user_secrets_enabled() -> None:
    if not config.SECRETS_MASTER_KEY:
        raise HTTPException(
            status_code=503,
            detail=(
                "AGENT_SECRETS_MASTER_KEY must be set on the server (operator only; "
                "encrypts stored secrets — end users never see or paste this)"
            ),
        )


def _norm_service_key(raw: str) -> str:
    k = (raw or "").strip().lower()
    if not _SERVICE_KEY_RE.fullmatch(k):
        raise HTTPException(
            status_code=400,
            detail="invalid service_key: use lowercase [a-z0-9._-], max 63 chars",
        )
    return k


class UserSecretBody(BaseModel):
    service_key: str = Field(..., min_length=1, max_length=64)
    secret: str = Field(..., min_length=1, max_length=65536)


class RegisterWithOtpBody(BaseModel):
    otp: str = Field(..., min_length=8, max_length=256)
    service_key: str = Field(..., min_length=1, max_length=64)
    secret: str = Field(..., min_length=1, max_length=65536)


@router.post("/register-with-otp")
def register_secret_with_otp(body: RegisterWithOtpBody):
    """
    Store a secret using a one-time code from the ``register_secrets`` tool (chat).
    No Bearer token or user headers — the OTP binds to the chat user who minted it.
    """
    _require_user_secrets_enabled()
    sk = _norm_service_key(body.service_key)
    try:
        db.user_secret_register_with_otp(body.otp, sk, body.secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"ok": True, "service_key": sk, "stored": True}


@router.get("")
def list_user_secrets(request: Request):
    """List configured service keys for this user (no secret values)."""
    _require_user_secrets_enabled()
    uid, _tid = resolve_user_tenant(request)
    return {"ok": True, "services": db.user_secret_list_service_keys(uid)}


@router.post("")
def upsert_user_secret(request: Request, body: UserSecretBody):
    """Store or replace an encrypted secret for this user."""
    _require_user_secrets_enabled()
    uid, _tid = resolve_user_tenant(request)
    sk = _norm_service_key(body.service_key)
    try:
        db.user_secret_upsert(uid, sk, body.secret)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "service_key": sk, "stored": True}


@router.delete("/{service_key}")
def delete_user_secret(service_key: str, request: Request):
    """Remove a stored secret."""
    _require_user_secrets_enabled()
    uid, _tid = resolve_user_tenant(request)
    sk = _norm_service_key(service_key)
    if not db.user_secret_delete(uid, sk):
        raise HTTPException(status_code=404, detail="no such secret for this user")
    return {"ok": True, "deleted": sk}
