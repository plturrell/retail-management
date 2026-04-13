"""Snowflake connection management.

snowflake-connector-python is synchronous. We wrap every call in
asyncio's thread-pool executor so it stays non-blocking in FastAPI.

Usage:
    async with get_snowflake() as sf:
        rows = await sf.fetch("SELECT COUNT(*) FROM FACT_SALES")
        await sf.execute("INSERT INTO ...")
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

import snowflake.connector
from snowflake.connector import DictCursor

from app.config import settings

logger = logging.getLogger(__name__)

_CONNECT_PARAMS: dict[str, str] = {}


def _build_connect_params() -> dict[str, str]:
    return {
        "account": settings.SNOWFLAKE_ACCOUNT,
        "user": settings.SNOWFLAKE_USER,
        "password": settings.SNOWFLAKE_PASSWORD,
        "database": settings.SNOWFLAKE_DATABASE,
        "schema": settings.SNOWFLAKE_SCHEMA,
        "warehouse": settings.SNOWFLAKE_WAREHOUSE,
        "role": settings.SNOWFLAKE_ROLE,
        "session_parameters": {
            "QUERY_TAG": "retailsg_api",
            "TIMEZONE": "Asia/Singapore",
        },
    }


class SnowflakeClient:
    """Thin async wrapper around a synchronous Snowflake connection."""

    def __init__(self, conn: snowflake.connector.SnowflakeConnection) -> None:
        self._conn = conn
        self._loop = asyncio.get_event_loop()

    def _run(self, fn, *args, **kwargs):
        """Run a sync callable in the thread pool executor."""
        return self._loop.run_in_executor(None, partial(fn, *args, **kwargs))

    async def execute(self, sql: str, params: tuple | dict | None = None) -> None:
        """Execute a DML or DDL statement (no result returned)."""
        def _exec():
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
        await self._run(_exec)

    async def executemany(self, sql: str, seq_of_params: list[tuple | dict]) -> None:
        """Batch execute for bulk inserts."""
        def _exec():
            with self._conn.cursor() as cur:
                cur.executemany(sql, seq_of_params)
        await self._run(_exec)

    async def fetch(
        self, sql: str, params: tuple | dict | None = None
    ) -> list[dict[str, Any]]:
        """Execute a SELECT and return all rows as dicts."""
        def _fetch() -> list[dict]:
            with self._conn.cursor(DictCursor) as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        return await self._run(_fetch)

    async def fetch_one(
        self, sql: str, params: tuple | dict | None = None
    ) -> dict[str, Any] | None:
        """Execute a SELECT and return the first row as a dict, or None."""
        rows = await self.fetch(sql, params)
        return rows[0] if rows else None

    async def use_schema(self, schema: str) -> None:
        await self.execute(f"USE SCHEMA {schema}")

    async def close(self) -> None:
        def _close():
            self._conn.close()
        await self._run(_close)


@asynccontextmanager
async def get_snowflake(
    schema: str | None = None,
) -> AsyncGenerator[SnowflakeClient, None]:
    """Async context manager yielding a connected SnowflakeClient.

    Args:
        schema: Override the default schema (e.g. pass ETL_SCHEMA for ETL work).
    """
    if not settings.SNOWFLAKE_ACCOUNT:
        raise RuntimeError(
            "Snowflake is not configured — set SNOWFLAKE_ACCOUNT in environment"
        )

    params = _build_connect_params()
    if schema:
        params["schema"] = schema

    loop = asyncio.get_event_loop()

    def _connect():
        return snowflake.connector.connect(**params)

    conn = await loop.run_in_executor(None, _connect)
    client = SnowflakeClient(conn)
    try:
        yield client
    except Exception as exc:
        logger.error("Snowflake operation failed: %s", exc, exc_info=True)
        raise
    finally:
        await client.close()


async def snowflake_is_available() -> bool:
    """Health-check: returns True if Snowflake is reachable."""
    try:
        async with get_snowflake() as sf:
            row = await sf.fetch_one("SELECT CURRENT_TIMESTAMP() AS ts")
            return row is not None
    except Exception as exc:
        logger.warning("Snowflake health check failed: %s", exc)
        return False
