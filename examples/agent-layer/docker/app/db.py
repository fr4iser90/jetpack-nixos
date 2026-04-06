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
    (
        5,
        """
        CREATE TABLE IF NOT EXISTS user_kb_notes (
          id BIGSERIAL PRIMARY KEY,
          tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL DEFAULT '',
          body TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          search_tsv tsvector GENERATED ALWAYS AS (
            to_tsvector(
              'simple',
              coalesce(title, '') || ' ' || coalesce(body, '')
            )
          ) STORED
        );

        CREATE INDEX IF NOT EXISTS idx_user_kb_notes_tenant_user_created
          ON user_kb_notes (tenant_id, user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_user_kb_notes_tsv
          ON user_kb_notes USING GIN (search_tsv);
        """,
    ),
    (
        6,
        """
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS rag_documents (
          id BIGSERIAL PRIMARY KEY,
          tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          domain TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          source_uri TEXT,
          content_sha256 TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_rag_documents_scope
          ON rag_documents (tenant_id, user_id, domain);

        CREATE TABLE IF NOT EXISTS rag_chunks (
          id BIGSERIAL PRIMARY KEY,
          document_id BIGINT NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
          chunk_index INT NOT NULL,
          content TEXT NOT NULL,
          embedding vector(768) NOT NULL,
          UNIQUE (document_id, chunk_index)
        );

        CREATE INDEX IF NOT EXISTS idx_rag_chunks_document
          ON rag_chunks (document_id);

        CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding
          ON rag_chunks USING hnsw (embedding vector_cosine_ops);
        """,
    ),
    (
        7,
        """
        CREATE TABLE IF NOT EXISTS rss_articles (
          id BIGSERIAL PRIMARY KEY,
          article_id TEXT NOT NULL UNIQUE,
          url TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT,
          fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_rss_articles_id ON rss_articles (article_id);
        CREATE INDEX IF NOT EXISTS idx_rss_articles_fetched ON rss_articles (fetched_at DESC);
        """,
    ),
    (
        9,
        """
        -- Convert users.id from BIGINT to UUID
        -- Safe migration, no data loss

        -- 1. Remove foreign keys
        ALTER TABLE refresh_tokens DROP CONSTRAINT IF EXISTS refresh_tokens_user_id_fkey;
        ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_user_id_fkey;
        ALTER TABLE workflows DROP CONSTRAINT IF EXISTS workflows_owner_user_id_fkey;
        ALTER TABLE workflow_permissions DROP CONSTRAINT IF EXISTS workflow_permissions_user_id_fkey;
        ALTER TABLE todos DROP CONSTRAINT IF EXISTS todos_user_id_fkey;
        ALTER TABLE tool_invocations DROP CONSTRAINT IF EXISTS tool_invocations_user_id_fkey;
        ALTER TABLE user_secrets DROP CONSTRAINT IF EXISTS user_secrets_user_id_fkey;
        ALTER TABLE secret_upload_otps DROP CONSTRAINT IF EXISTS secret_upload_otps_user_id_fkey;
        ALTER TABLE user_kb_notes DROP CONSTRAINT IF EXISTS user_kb_notes_user_id_fkey;
        ALTER TABLE rag_documents DROP CONSTRAINT IF EXISTS rag_documents_user_id_fkey;

        -- 2. Prepare users table
        ALTER TABLE users ALTER COLUMN id DROP DEFAULT;
        DROP SEQUENCE IF EXISTS users_id_seq CASCADE;

        -- 3. Add temporary uuid column
        ALTER TABLE users ADD COLUMN uuid UUID UNIQUE DEFAULT gen_random_uuid();
        UPDATE users SET uuid = ('00000000-0000-4000-8000-' || lpad(to_hex(id), 12, '0'))::uuid WHERE id < 1000000;

        -- 4. FIRST convert foreign key columns to TEXT
        ALTER TABLE refresh_tokens ALTER COLUMN user_id TYPE TEXT;
        ALTER TABLE api_keys ALTER COLUMN user_id TYPE TEXT;
        ALTER TABLE workflows ALTER COLUMN owner_user_id TYPE TEXT;
        ALTER TABLE workflow_permissions ALTER COLUMN user_id TYPE TEXT;
        ALTER TABLE todos ALTER COLUMN user_id TYPE TEXT;
        ALTER TABLE tool_invocations ALTER COLUMN user_id TYPE TEXT;
        ALTER TABLE user_secrets ALTER COLUMN user_id TYPE TEXT;
        ALTER TABLE secret_upload_otps ALTER COLUMN user_id TYPE TEXT;
        ALTER TABLE user_kb_notes ALTER COLUMN user_id TYPE TEXT;
        ALTER TABLE rag_documents ALTER COLUMN user_id TYPE TEXT;

        -- 5. Update ALL foreign keys NOW
        UPDATE refresh_tokens SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);
        UPDATE api_keys SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);
        UPDATE workflows SET owner_user_id = (SELECT uuid::text FROM users WHERE id = owner_user_id::bigint);
        UPDATE workflow_permissions SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);
        UPDATE todos SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);
        UPDATE tool_invocations SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);
        UPDATE user_secrets SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);
        UPDATE secret_upload_otps SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);
        UPDATE user_kb_notes SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);
        UPDATE rag_documents SET user_id = (SELECT uuid::text FROM users WHERE id = user_id::bigint);

        -- 6. Switch primary key
        ALTER TABLE users DROP CONSTRAINT users_pkey CASCADE;
        ALTER TABLE users DROP COLUMN id;
        ALTER TABLE users RENAME COLUMN uuid TO id;
        ALTER TABLE users ADD PRIMARY KEY (id);

        -- 7. Convert all foreign key columns to UUID
        ALTER TABLE refresh_tokens ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
        ALTER TABLE api_keys ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
        ALTER TABLE workflows ALTER COLUMN owner_user_id TYPE UUID USING owner_user_id::uuid;
        ALTER TABLE workflow_permissions ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
        ALTER TABLE todos ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
        ALTER TABLE tool_invocations ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
        ALTER TABLE user_secrets ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
        ALTER TABLE secret_upload_otps ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
        ALTER TABLE user_kb_notes ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
        ALTER TABLE rag_documents ALTER COLUMN user_id TYPE UUID USING user_id::uuid;

        -- 7. Restore foreign keys
        ALTER TABLE refresh_tokens ADD CONSTRAINT refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE api_keys ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE workflows ADD CONSTRAINT workflows_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE workflow_permissions ADD CONSTRAINT workflow_permissions_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE todos ADD CONSTRAINT todos_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE tool_invocations ADD CONSTRAINT tool_invocations_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE user_secrets ADD CONSTRAINT user_secrets_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE secret_upload_otps ADD CONSTRAINT secret_upload_otps_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE user_kb_notes ADD CONSTRAINT user_kb_notes_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        ALTER TABLE rag_documents ADD CONSTRAINT rag_documents_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        """,
    ),
    (
        10,
        """
        -- Auth System Tables
        ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT UNIQUE;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';
        ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

        CREATE TABLE IF NOT EXISTS refresh_tokens (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          expires_at TIMESTAMPTZ NOT NULL,
          last_used_at TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);

        CREATE TABLE IF NOT EXISTS api_keys (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          key_hash TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_used_at TIMESTAMPTZ,
          expires_at TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
        CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);

        -- Workflow System
        CREATE TABLE IF NOT EXISTS workflows (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          description TEXT,
          definition JSONB NOT NULL DEFAULT '{}'::jsonb,
          visibility TEXT NOT NULL DEFAULT 'private',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_workflows_owner ON workflows(owner_user_id);

        CREATE TABLE IF NOT EXISTS workflow_permissions (
          workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          can_execute BOOLEAN NOT NULL DEFAULT false,
          can_edit BOOLEAN NOT NULL DEFAULT false,
          granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (workflow_id, user_id)
        );
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
        raise RuntimeError(
            "PostgreSQL connection missing: DATABASE_URL is empty and could not be built from "
            "POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB (and PGHOST defaulting to postgres). "
            "Fix: set DATABASE_URL in docker/.env (see .env.example), or pass the same POSTGRES_* "
            "variables into the agent-layer container as for the postgres service, then restart."
        )
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
    args_for_db: Any = args
    if isinstance(args, dict):
        redact = config.tool_log_redact_keys()
        if redact:
            args_for_db = {}
            for k, v in args.items():
                if k in redact and isinstance(v, str) and len(v) > 200:
                    args_for_db[k] = f"<omitted {len(v)} chars>"
                else:
                    args_for_db[k] = v
    try:
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_invocations
                      (tool_name, args_json, result_excerpt, ok, tenant_id, user_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (tool_name, Json(args_for_db), excerpt, ok, tenant_id, user_id),
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


def user_secret_register_with_otp(
    otp_raw: str, service_key: str, plaintext: str
) -> None:
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
                SELECT user_id, used_at, expires_at
                FROM secret_upload_otps
                WHERE otp_hash = %s
                FOR UPDATE
                """,
                (otp_hash,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(
                    "unknown otp — check copy/paste (no spaces/line breaks), or mint a new one with register_secrets"
                )
            uid = int(row[0])
            used_at = row[1]
            expires_at = row[2]
            if used_at is not None:
                raise ValueError(
                    "otp already used (single-use) — call register_secrets again for a new curl_bash"
                )
            now_utc = datetime.now(UTC)
            if expires_at is not None:
                exp = expires_at
                if getattr(exp, "tzinfo", None) is None:
                    exp = exp.replace(tzinfo=UTC)
                if exp <= now_utc:
                    raise ValueError(
                        "otp expired — default validity 10 min; call register_secrets again"
                    )
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


def kb_note_append(title: str, body: str) -> int:
    tenant_id, user_id = identity.get_identity()
    title = (title or "").strip()
    body = (body or "").strip()
    if not body:
        raise ValueError("body is required")
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_kb_notes (title, body, tenant_id, user_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (title, body, tenant_id, user_id),
            )
            row = cur.fetchone()
            nid = int(row[0])
        conn.commit()
    return nid


def _ilike_contains(s: str) -> str:
    esc = s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def kb_note_search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    tenant_id, user_id = identity.get_identity()
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 20), 50))
    pat = _ilike_contains(q)
    sql_full = """
                SELECT id, title, left(body, 500) AS body_excerpt, created_at
                FROM user_kb_notes
                WHERE tenant_id = %s AND user_id = %s
                  AND (
                    title ILIKE %s ESCAPE '\\'
                    OR body ILIKE %s ESCAPE '\\'
                    OR search_tsv @@ websearch_to_tsquery('simple', %s)
                  )
                ORDER BY created_at DESC
                LIMIT %s
                """
    sql_ilike = """
                SELECT id, title, left(body, 500) AS body_excerpt, created_at
                FROM user_kb_notes
                WHERE tenant_id = %s AND user_id = %s
                  AND (
                    title ILIKE %s ESCAPE '\\'
                    OR body ILIKE %s ESCAPE '\\'
                  )
                ORDER BY created_at DESC
                LIMIT %s
                """
    with pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute(
                    sql_full,
                    (tenant_id, user_id, pat, pat, q, limit),
                )
            except psycopg.Error:
                logger.debug(
                    "kb_note_search fts fallback for query %r", q[:80], exc_info=True
                )
                conn.rollback()
                cur.execute(
                    sql_ilike,
                    (tenant_id, user_id, pat, pat, limit),
                )
            rows = cur.fetchall()
        conn.commit()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "title": r["title"],
                "body_excerpt": r["body_excerpt"],
                "created_at": (
                    r["created_at"].isoformat() if r.get("created_at") else None
                ),
            }
        )
    return out


def kb_note_get(note_id: int, max_body_chars: int = 12000) -> dict[str, Any] | None:
    tenant_id, user_id = identity.get_identity()
    max_body_chars = max(500, min(int(max_body_chars or 12000), 100_000))
    with pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, title, body, created_at, updated_at
                FROM user_kb_notes
                WHERE id = %s AND tenant_id = %s AND user_id = %s
                """,
                (note_id, tenant_id, user_id),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        return None
    body = str(row["body"] or "")
    if len(body) > max_body_chars:
        body = body[:max_body_chars] + "\n… (truncated)"
    return {
        "id": row["id"],
        "title": row["title"],
        "body": body,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


def rag_document_and_chunks_insert(
    tenant_id: int,
    user_id: int,
    domain: str,
    title: str,
    source_uri: str | None,
    content_sha256: str,
    chunks: list[tuple[int, str, list[float]]],
) -> tuple[int, int]:
    """
    Insert one ``rag_documents`` row and its chunks (each with embedding).
    Returns ``(document_id, chunk_count)``. Caller must validate embedding dims.
    """
    if not chunks:
        raise ValueError("chunks must be non-empty")
    domain = (domain or "").strip()
    title = (title or "").strip()
    uri = (source_uri or "").strip() or None
    sha = (content_sha256 or "").strip() or None
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rag_documents
                  (tenant_id, user_id, domain, title, source_uri, content_sha256)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (tenant_id, user_id, domain, title, uri, sha),
            )
            doc_id = int(cur.fetchone()[0])
            for idx, content, emb in chunks:
                cur.execute(
                    """
                    INSERT INTO rag_chunks (document_id, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s::vector)
                    """,
                    (doc_id, int(idx), content, _vector_literal(emb)),
                )
        conn.commit()
    return doc_id, len(chunks)


def rag_vector_search(
    tenant_id: int,
    user_id: int,
    query_embedding: list[float],
    domain: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Cosine distance (pgvector ``<=>``); lower is more similar."""
    limit = max(1, min(int(limit), 50))
    dom = (domain or "").strip()
    qv = _vector_literal(query_embedding)
    with pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                  c.id AS chunk_id,
                  c.chunk_index,
                  left(c.content, 8000) AS content,
                  d.id AS document_id,
                  d.title,
                  d.domain,
                  (c.embedding <=> %s::vector) AS distance
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id
                WHERE d.tenant_id = %s
                  AND d.user_id = %s
                  AND (%s = '' OR d.domain = %s)
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s
                """,
                (qv, tenant_id, user_id, dom, dom, qv, limit),
            )
            rows = cur.fetchall()
        conn.commit()
    out: list[dict[str, Any]] = []
    for r in rows:
        dist = r.get("distance")
        out.append(
            {
                "chunk_id": r["chunk_id"],
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "document_id": r["document_id"],
                "title": r["title"],
                "domain": r["domain"],
                "distance": float(dist) if dist is not None else None,
            }
        )
    return out