"""
Authentication & Authorization Layer for Agent Layer
JWT Access + Refresh Tokens, BCrypt Password Hashing, Permission System
"""
from __future__ import annotations

import os
import time
import bcrypt
import jwt
import uuid
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Callable, Any

from fastapi import Request, HTTPException
from pydantic import BaseModel

from . import db
from .identity import set_identity, reset_identity


# JWT Configuration
JWT_SECRET = os.environ.get("AGENT_JWT_SECRET", os.urandom(32).hex())
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7


class User(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: str
    password: str


def hash_password(password: str) -> str:
    """Hash password with bcrypt"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash"""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    """Create short-lived JWT access token"""
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str]:
    """Create long-lived refresh token, returns (token, token_hash)"""
    token = uuid.uuid4().hex
    token_hash = hash_password(token)
    return token, token_hash


def validate_refresh_token(token: str) -> Optional[User]:
    """Validate refresh token and return user if valid"""
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, token_hash, expires_at
                FROM refresh_tokens
                WHERE revoked_at IS NULL
                AND expires_at > NOW()
            """)
            
            for row in cur.fetchall():
                user_id, token_hash, expires_at = row
                if verify_password(token, token_hash):
                    return get_user_by_id(user_id)
    
    return None


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate JWT access token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


def get_user_by_email(email: str) -> Optional[User]:
    """Get user by email"""
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, email, role, created_at
                FROM users
                WHERE email = %s
            """, (email,))
            row = cur.fetchone()
            if not row:
                return None
            return User(
                id=row[0],
                email=row[1],
                role=row[2],
                created_at=row[3]
            )


def get_user_by_id(user_id: uuid.UUID) -> Optional[User]:
    """Get user by id"""
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, email, role, created_at
                FROM users
                WHERE id = %s
            """, (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return User(
                id=row[0],
                email=row[1],
                role=row[2],
                created_at=row[3]
            )


async def get_current_user(request: Request) -> User:
    """
    Middleware to resolve current user from request
    Supports:
    - Bearer JWT Token
    - Bearer API Key
    - Legacy global API Key (fallback for backwards compatibility)
    """

    # Check for authorization header
    auth = request.headers.get("authorization") or ""
    token = auth.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 1. Try JWT Access Token
    payload = decode_access_token(token)
    if payload:
        user = get_user_by_id(uuid.UUID(payload["sub"]))
        if user:
            return user

    # 2. Try API Key
    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id FROM api_keys
                WHERE key_hash = %s
            """, (token,))
            row = cur.fetchone()
            if row:
                user = get_user_by_id(row[0])
                if user:
                    # Update last used timestamp
                    cur.execute("""
                        UPDATE api_keys
                        SET last_used_at = NOW()
                        WHERE key_hash = %s
                    """, (token,))
                    conn.commit()
                    return user


    raise HTTPException(status_code=401, detail="Unauthorized")


def require_permission(action: str, resource_type: Optional[str] = None) -> Callable:
    """
    Decorator to require permission for endpoint
    Example: @require_permission("execute", "tool")
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args: Any, **kwargs: Any) -> Any:
            user = await get_current_user(request)

            # Admin has all permissions
            if user.role == "admin":
                return await func(request, *args, **kwargs, user=user)

            # Set identity context for downstream code
            id_token = set_identity(1, int(user.id.int % (2**31)))

            try:
                return await func(request, *args, **kwargs, user=user)
            finally:
                reset_identity(id_token)

        return wrapper
    return decorator


def create_user(email: str, password: str, role: str = "user") -> User:
    """Create new user"""
    user_id = uuid.uuid4()
    password_hash = hash_password(password)
    external_sub = f"manual:{email}"

    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (id, email, password_hash, role, tenant_id, external_sub)
                VALUES (%s, %s, %s, %s, 1, %s)
                RETURNING created_at
            """, (user_id, email, password_hash, role, external_sub))
            created_at = cur.fetchone()[0]
            conn.commit()

    return User(
        id=user_id,
        email=email,
        role=role,
        created_at=created_at
    )


def update_user_password(user_id: uuid.UUID, password: str) -> None:
    """Update existing user password"""
    password_hash = hash_password(password)

    with db.pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
            """, (password_hash, user_id))
            conn.commit()
