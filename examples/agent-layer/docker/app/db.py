"""PostgreSQL pool, schema migrations, and persistence helpers."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from . import config
from . import identity

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None

# (version, sql) — applied in order; version must be unique and increasing
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS todos (
          id BIGSERIAL PRIMARY KEY,
          title TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT todos_status_check CHECK (status IN ('open', 'done', 'cancelled'))
        );

        CREATE INDEX IF NOT EXISTS idx_todos_created_at ON todos (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_todos_status ON todos (status);

        CREATE TABLE IF NOT EXISTS tool_invocations (
          id BIGSERIAL PRIMARY KEY,
          tool_name TEXT NOT NULL,
          args_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          result_excerpt TEXT,
          ok BOOLEAN NOT NULL DEFAULT true,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_tool_invocations_created_at
          ON tool_invocations (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool_name
          ON tool_invocations (tool_name);
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS tenants (
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL DEFAULT '',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS users (
          id BIGSERIAL PRIMARY KEY,
          tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          external_sub TEXT NOT NULL,
          display_name TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, external_sub)
        );

        CREATE INDEX IF NOT EXISTS idx_users_tenant ON users (tenant_id);
        CREATE INDEX IF NOT EXISTS idx_users_tenant_sub ON users (tenant_id, external_sub);

        INSERT INTO tenants (id, name) VALUES (1, 'default')
        ON CONFLICT (id) DO NOTHING;

        SELECT setval(
          pg_get_serial_sequence('tenants', 'id'),
          GREATEST((SELECT COALESCE(MAX(id), 1) FROM tenants), 1)
        );

        INSERT INTO users (id, tenant_id, external_sub, display_name)
        VALUES (1, 1, 'default', 'Default user')
        ON CONFLICT (tenant_id, external_sub) DO NOTHING;

        SELECT setval(
          pg_get_serial_sequence('users', 'id'),
          GREATEST((SELECT COALESCE(MAX(id), 1) FROM users), 1)
        );

        ALTER TABLE todos ADD COLUMN IF NOT EXISTS tenant_id BIGINT;
        ALTER TABLE todos ADD COLUMN IF NOT EXISTS user_id BIGINT;
        UPDATE todos SET tenant_id = 1 WHERE tenant_id IS NULL;
        UPDATE todos SET user_id = 1 WHERE user_id IS NULL;
        ALTER TABLE todos ALTER COLUMN tenant_id SET NOT NULL;
        ALTER TABLE todos ALTER COLUMN user_id SET NOT NULL;
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'todos_tenant_id_fkey'
          ) THEN
            ALTER TABLE todos ADD CONSTRAINT todos_tenant_id_fkey
              FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'todos_user_id_fkey'
          ) THEN
            ALTER TABLE todos ADD CONSTRAINT todos_user_id_fkey
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
          END IF;
        END $$;

        CREATE INDEX IF NOT EXISTS idx_todos_tenant_user_created
          ON todos (tenant_id, user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_todos_user_status ON todos (user_id, status);

        ALTER TABLE tool_invocations ADD COLUMN IF NOT EXISTS tenant_id BIGINT;
        ALTER TABLE tool_invocations ADD COLUMN IF NOT EXISTS user_id BIGINT;
        UPDATE tool_invocations SET tenant_id = 1 WHERE tenant_id IS NULL;
        UPDATE tool_invocations SET user_id = 1 WHERE user_id IS NULL;
        ALTER TABLE tool_invocations ALTER COLUMN tenant_id SET NOT NULL;
        ALTER TABLE tool_invocations ALTER COLUMN user_id SET NOT NULL;
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'tool_invocations_tenant_id_fkey'
          ) THEN
            ALTER TABLE tool_invocations ADD CONSTRAINT tool_invocations_tenant_id_fkey
              FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'tool_invocations_user_id_fkey'
          ) THEN
            ALTER TABLE tool_invocations ADD CONSTRAINT tool_invocations_user_id_fkey
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
          END IF;
        END $$;

        CREATE INDEX IF NOT EXISTS idx_tool_inv_user_created
          ON tool_invocations (user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_tool_inv_tenant_user
          ON tool_invocations (tenant_id, user_id);
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS user_secrets (
          id BIGSERIAL PRIMARY KEY,
          user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          service_key TEXT NOT NULL,
          ciphertext BYTEA NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (user_id, service_key)
        );

        CREATE INDEX IF NOT EXISTS idx_user_secrets_user
          ON user_secrets (user_id);
        """,
    ),
    (
        4,
        """
        CREATE TABLE IF NOT EXISTS secret_upload_otps (
          id BIGSERIAL PRIMARY KEY,
          user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          otp_hash TEXT NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL,
          used_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_secret_otps_hash_unused
          ON secret_upload_otps (otp_hash)
          WHERE used_at IS NULL;
        """,
    ),
]


def pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("database pool not initialized")
    return _pool


def init_pool() -> None:
    global _pool
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required (PostgreSQL)")
    if _pool is not None:
        return
    _pool = ConnectionPool(
        conninfo=config.DATABASE_URL,
        min_size=1,
        max_size=10,
        kwargs={"autocommit": False},
    )
    logger.info("PostgreSQL pool ready")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def migrate() -> None:
    p = pool()
    with p.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version INT PRIMARY KEY,
                  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        conn.commit()

    with p.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations ORDER BY version")
            applied = {row[0] for row in cur.fetchall()}

        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            logger.info("Applying DB migration %s", version)
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            conn.commit()


def ensure_user_external(external_sub: str, tenant_id: int) -> tuple[int, int]:
    """
    Resolve or create ``users`` row. ``external_sub`` is a stable id from the client
    (e.g. OIDC sub or WebUI user id string). Returns ``(user_id, tenant_id)``.
    """
    sub = (external_sub or "").strip() or "default"
    tid = int(tenant_id) if tenant_id else 1
    if tid < 1:
        tid = 1
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tenants WHERE id = %s", (tid,))
            if cur.fetchone() is None:
                tid = 1
            cur.execute(
                "SELECT id FROM users WHERE tenant_id = %s AND external_sub = %s",
                (tid, sub),
            )
            row = cur.fetchone()
            if row:
                uid = int(row[0])
            else:
                cur.execute(
                    """
                    INSERT INTO users (tenant_id, external_sub)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (tid, sub),
                )
                uid = int(cur.fetchone()[0])
        conn.commit()
    return uid, tid


def user_external_sub(user_id: int) -> str | None:
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT external_sub FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        return None
    return str(row[0]) if row[0] is not None else None


def todo_create(title: str) -> int:
    tenant_id, user_id = identity.get_identity()
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO todos (title, tenant_id, user_id)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (title, tenant_id, user_id),
            )
            row = cur.fetchone()
            tid = int(row[0])
        conn.commit()
        return tid


def todo_list(limit: int = 100) -> list[dict[str, Any]]:
    tenant_id, user_id = identity.get_identity()
    with pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, title, status, created_at, updated_at
                FROM todos
                WHERE tenant_id = %s AND user_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (tenant_id, user_id, limit),
            )
            rows = cur.fetchall()
        conn.commit()
    return [dict(r) for r in rows]


def todo_set_status(todo_id: int, status: str) -> bool:
    tenant_id, user_id = identity.get_identity()
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE todos
                SET status = %s, updated_at = now()
                WHERE id = %s AND tenant_id = %s AND user_id = %s
                """,
                (status, todo_id, tenant_id, user_id),
            )
            n = cur.rowcount
        conn.commit()
    return n > 0


def log_tool_invocation(
    tool_name: str,
    args: dict[str, Any],
    result_text: str,
    ok: bool,
) -> None:
    excerpt = (result_text or "")[:4000]
    tenant_id, user_id = identity.get_identity()
    try:
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_invocations
                      (tool_name, args_json, result_excerpt, ok, tenant_id, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (tool_name, Json(args), excerpt, ok, tenant_id, user_id),
                )
            conn.commit()
    except psycopg.Error:
        logger.exception("failed to log tool_invocation for %s", tool_name)


def recent_tool_invocations(limit: int = 50) -> list[dict[str, Any]]:
    tenant_id, user_id = identity.get_identity()
    with pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, tool_name, args_json, result_excerpt, ok, created_at,
                       tenant_id, user_id
                FROM tool_invocations
                WHERE tenant_id = %s AND user_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (tenant_id, user_id, limit),
            )
            rows = cur.fetchall()
        conn.commit()
    return [dict(r) for r in rows]


def user_secret_upsert(user_id: int, service_key: str, plaintext: str) -> None:
    from . import crypto_secrets

    ct = crypto_secrets.encrypt_secret(plaintext)
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_secrets (user_id, service_key, ciphertext)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, service_key) DO UPDATE SET
                  ciphertext = EXCLUDED.ciphertext,
                  updated_at = now()
                """,
                (user_id, service_key, ct),
            )
        conn.commit()


def user_secret_get_plaintext(user_id: int, service_key: str) -> str | None:
    """Server-side only — never return this to LLM tool JSON."""
    from . import crypto_secrets

    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ciphertext FROM user_secrets
                WHERE user_id = %s AND service_key = %s
                """,
                (user_id, service_key),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        return None
    return crypto_secrets.decrypt_secret(bytes(row[0]))


def user_secret_delete(user_id: int, service_key: str) -> bool:
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM user_secrets
                WHERE user_id = %s AND service_key = %s
                """,
                (user_id, service_key),
            )
            n = cur.rowcount
        conn.commit()
    return n > 0


def user_secret_list_service_keys(user_id: int) -> list[str]:
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT service_key FROM user_secrets
                WHERE user_id = %s
                ORDER BY service_key
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        conn.commit()
    return [str(r[0]) for r in rows]


def secret_upload_otp_create(user_id: int, ttl_seconds: int = 600) -> str:
    """Insert a one-time registration token; return plaintext OTP (show once)."""
    raw = secrets.token_urlsafe(18)
    otp_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO secret_upload_otps (user_id, otp_hash, expires_at)
                VALUES (%s, %s, %s)
                """,
                (user_id, otp_hash, expires),
            )
        conn.commit()
    return raw


def user_secret_register_with_otp(otp_raw: str, service_key: str, plaintext: str) -> None:
    """Validate OTP (single-use), then upsert encrypted secret for bound user."""
    from . import crypto_secrets

    otp_raw = (otp_raw or "").strip()
    if not otp_raw:
        raise ValueError("otp is required")
    otp_hash = hashlib.sha256(otp_raw.encode("utf-8")).hexdigest()
    ct = crypto_secrets.encrypt_secret(plaintext)
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id FROM secret_upload_otps
                WHERE otp_hash = %s AND used_at IS NULL AND expires_at > now()
                FOR UPDATE
                """,
                (otp_hash,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("invalid or expired otp")
            uid = int(row[0])
            cur.execute(
                """
                UPDATE secret_upload_otps SET used_at = now()
                WHERE otp_hash = %s AND used_at IS NULL
                """,
                (otp_hash,),
            )
            cur.execute(
                """
                INSERT INTO user_secrets (user_id, service_key, ciphertext)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, service_key) DO UPDATE SET
                  ciphertext = EXCLUDED.ciphertext,
                  updated_at = now()
                """,
                (uid, service_key, ct),
            )
        conn.commit()
