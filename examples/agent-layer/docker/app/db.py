"""PostgreSQL pool, schema migrations, and persistence helpers."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from . import config

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


def todo_create(title: str) -> int:
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO todos (title) VALUES (%s) RETURNING id",
                (title,),
            )
            row = cur.fetchone()
            tid = int(row[0])
        conn.commit()
        return tid


def todo_list(limit: int = 100) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, title, status, created_at, updated_at
                FROM todos
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        conn.commit()
    return [dict(r) for r in rows]


def todo_set_status(todo_id: int, status: str) -> bool:
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE todos
                SET status = %s, updated_at = now()
                WHERE id = %s
                """,
                (status, todo_id),
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
    try:
        with pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_invocations
                      (tool_name, args_json, result_excerpt, ok)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (tool_name, Json(args), excerpt, ok),
                )
            conn.commit()
    except psycopg.Error:
        logger.exception("failed to log tool_invocation for %s", tool_name)


def recent_tool_invocations(limit: int = 50) -> list[dict[str, Any]]:
    with pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, tool_name, args_json, result_excerpt, ok, created_at
                FROM tool_invocations
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        conn.commit()
    return [dict(r) for r in rows]
