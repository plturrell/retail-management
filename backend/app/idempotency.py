"""Idempotency-Key support for multi-write endpoints.

Used to make safe-to-retry the master-data endpoints that mutate Firestore +
the master JSON in one call (price publish, invoice commit, manual create).
A client that sees a network error mid-request can retry with the same
``Idempotency-Key`` header and receive the original response instead of
re-executing the work.

Scope: in-memory only. Doesn't survive a process restart and isn't shared
across replicas. That's acceptable for the current single-replica deployment;
if we ever scale this out, swap the backing store for Firestore or Redis
without changing the call sites.

Cache key is ``(actor_email, scope, header_value)`` — same key from two
different users (or two different endpoints) doesn't collide.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from fastapi import HTTPException
from starlette.requests import Request

HEADER_NAME = "Idempotency-Key"

# Conservative bounds — keep memory predictable on a small box.
_MAX_ENTRIES = 1000
_TTL_SECONDS = 24 * 60 * 60
_MAX_KEY_LEN = 200

_cache_lock = threading.RLock()
# full_key -> (expires_at_epoch, response_dict)
_cache: "dict[str, tuple[float, dict]]" = {}
# full_key -> per-key lock; concurrent identical requests serialise so the
# second one sees the first one's cached response instead of re-running.
_inflight_locks: "dict[str, threading.Lock]" = {}


def _actor_email(actor: Any) -> str:
    raw = actor.get("email") if isinstance(actor, dict) else getattr(actor, "email", None)
    return (raw or "").strip().lower()


def _read_header(request: Request) -> Optional[str]:
    raw = request.headers.get(HEADER_NAME)
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if len(key) > _MAX_KEY_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"{HEADER_NAME} must be {_MAX_KEY_LEN} chars or fewer.",
        )
    return key


def _full_key(actor_email: str, scope: str, key: str) -> str:
    return f"{actor_email}|{scope}|{key}"


def _evict_locked() -> None:
    """Caller must hold ``_cache_lock``."""
    now = time.time()
    expired = [k for k, (exp, _) in _cache.items() if exp <= now]
    for k in expired:
        _cache.pop(k, None)
    if len(_cache) > _MAX_ENTRIES:
        # Drop the oldest entries by expiry; cheap & deterministic.
        for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[: len(_cache) - _MAX_ENTRIES]:
            _cache.pop(k, None)


def _get_or_create_inflight_lock(full_key: str) -> threading.Lock:
    with _cache_lock:
        lock = _inflight_locks.get(full_key)
        if lock is None:
            lock = threading.Lock()
            _inflight_locks[full_key] = lock
        return lock


class _Guard:
    """Returned by :func:`guard`; exposes the cached response (if any) and a
    ``store`` method the caller invokes on success."""

    def __init__(self, full_key: str, inflight_lock: threading.Lock) -> None:
        self._full_key = full_key
        self._inflight_lock = inflight_lock
        self.cached: Optional[dict] = None

    def store(self, response: dict) -> None:
        with _cache_lock:
            _cache[self._full_key] = (time.time() + _TTL_SECONDS, response)
            _evict_locked()


@contextmanager
def guard(request: Request, scope: str, actor: Any) -> Iterator[Optional[_Guard]]:
    """Context manager protecting an idempotent endpoint body.

    Usage::

        with idempotency.guard(request, "publish_prices_bulk", actor) as g:
            if g is not None and g.cached is not None:
                return g.cached
            result = do_work()
            if g is not None:
                g.store(result)
            return result

    Yields ``None`` if the caller didn't send an ``Idempotency-Key`` header —
    in that case the endpoint runs normally with no caching. Otherwise yields
    a guard whose ``cached`` is set when a previous successful response is on
    file. Concurrent calls with the same key serialise on a per-key lock so
    the second caller observes the first caller's stored response.
    """
    key = _read_header(request)
    if key is None:
        yield None
        return

    actor_email = _actor_email(actor)
    full_key = _full_key(actor_email, scope, key)
    inflight_lock = _get_or_create_inflight_lock(full_key)
    inflight_lock.acquire()
    try:
        with _cache_lock:
            entry = _cache.get(full_key)
            if entry is not None and entry[0] > time.time():
                hit = _Guard(full_key, inflight_lock)
                hit.cached = entry[1]
                yield hit
                return
        # No cached response — caller will run, then call store().
        yield _Guard(full_key, inflight_lock)
    finally:
        inflight_lock.release()
        # Best-effort cleanup of the per-key lock once nobody is waiting on
        # it; safe because acquire happens under no other lock.
        with _cache_lock:
            existing = _inflight_locks.get(full_key)
            if existing is inflight_lock and not inflight_lock.locked():
                _inflight_locks.pop(full_key, None)


def _reset_for_tests() -> None:
    """Test-only: clear all cached responses and per-key locks."""
    with _cache_lock:
        _cache.clear()
        _inflight_locks.clear()
