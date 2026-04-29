"""Async SQLAlchemy engine + session helpers for TiDB Cloud / MySQL.

Design notes
------------
- The TiDB layer is *optional*. If `settings.TIDB_DATABASE_URL` is empty the
  engine is `None` and `get_session()` raises 503; callers that dual-write
  must catch this and continue against Firestore so the SQL outage doesn't
  break the request.
- TLS is on by default for TiDB Serverless. Drivers pick up system CA roots;
  if `TIDB_SSL_CA` is set we pass it through `connect_args["ssl"]["ca"]`.
- Sessions are async, expire-on-commit off (so callers can read from the
  returned ORM object after `commit()`).
"""
from __future__ import annotations

import logging
import ssl
from typing import AsyncIterator, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

logger = logging.getLogger(__name__)


def _build_engine() -> Optional[AsyncEngine]:
    url = (settings.TIDB_DATABASE_URL or "").strip()
    if not url:
        logger.info("TIDB_DATABASE_URL is unset — TiDB layer disabled.")
        return None

    connect_args: dict = {}
    # asyncmy uses an `ssl` connect arg accepting an `ssl.SSLContext`. For TiDB
    # Serverless we need TLS; build a default verifying context, optionally
    # pinned to a custom CA file.
    if url.startswith("mysql+asyncmy://"):
        ssl_ctx = ssl.create_default_context(cafile=settings.TIDB_SSL_CA or None)
        ssl_ctx.check_hostname = True
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED
        connect_args["ssl"] = ssl_ctx

    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=1800,  # TiDB drops idle conns; recycle every 30 min.
        connect_args=connect_args,
    )


# Lazily-created so importing this module doesn't connect to anything.
_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def _ensure_initialised() -> None:
    global _engine, _sessionmaker
    if _engine is not None or not (settings.TIDB_DATABASE_URL or "").strip():
        return
    engine = _build_engine()
    if engine is None:
        return
    _engine = engine
    _sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def is_enabled() -> bool:
    """True iff a TiDB / SQL connection is configured."""
    return bool((settings.TIDB_DATABASE_URL or "").strip())


def get_engine() -> Optional[AsyncEngine]:
    """Return the engine, creating it on first call. None when disabled."""
    _ensure_initialised()
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async session.

    Raises 503 when the TiDB layer is disabled — callers that dual-write
    should call `is_enabled()` first and skip the SQL leg gracefully instead
    of using this dependency.
    """
    _ensure_initialised()
    if _sessionmaker is None:
        raise HTTPException(
            status_code=503,
            detail="TiDB layer is not configured (TIDB_DATABASE_URL is empty).",
        )
    async with _sessionmaker() as session:
        yield session


async def healthcheck() -> dict:
    """Probe the TiDB connection. Returns a structured dict, never raises."""
    if not is_enabled():
        return {"status": "disabled", "detail": "TIDB_DATABASE_URL is empty"}
    engine = get_engine()
    assert engine is not None
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text

            # Run a connectivity probe that works on every supported dialect,
            # then ask for the server version using a dialect-appropriate
            # function (mysql / tidb -> VERSION(); sqlite -> sqlite_version()).
            await conn.execute(text("SELECT 1"))

            dialect = engine.dialect.name
            if dialect in {"mysql", "mariadb"}:
                result = await conn.execute(text("SELECT VERSION()"))
            elif dialect == "sqlite":
                result = await conn.execute(text("SELECT sqlite_version()"))
            else:
                result = None

            version = None
            if result is not None:
                row = result.first()
                version = row[0] if row is not None else None
            return {
                "status": "ok",
                "dialect": dialect,
                "version": version,
            }
    except Exception as exc:  # noqa: BLE001 — health probes must never raise
        logger.warning("TiDB healthcheck failed: %s", exc)
        return {"status": "error", "detail": str(exc)}
