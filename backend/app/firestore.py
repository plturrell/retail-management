"""
Firestore client initialization for RetailSG.

Initializes firebase-admin and provides a Firestore client instance
and a FastAPI dependency for injection.
"""
from __future__ import annotations

import os
import logging
import sys
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.config import settings

logger = logging.getLogger(__name__)

_app: Optional[firebase_admin.App] = None
_db: Optional[FirestoreClient] = None


class FirestoreAuthError(RuntimeError):
    """Raised when Firestore credentials are missing, expired, or invalid."""


_AUTH_HINT = """
Firestore credentials are missing or expired.

Fix one of these:
  1. Service account (recommended -- doesn't expire):
       export GOOGLE_APPLICATION_CREDENTIALS=$HOME/.config/retailsg/retail-tools-firestore.json
  2. User ADC (expires hourly):
       gcloud auth application-default login
  3. Stale fallback to JSON snapshot (last successful export):
       python tools/scripts/export_nec_jewel.py --from-json
""".strip()


def _is_auth_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in (
        "invalid_grant",
        "unauthenticated",
        "could not automatically determine credentials",
        "default credentials were not found",
        "reauth",
    ))


def _materialise_credentials_from_env() -> None:
    """Support platforms (Railway, Fly, etc.) that can only inject env vars.

    If `GOOGLE_APPLICATION_CREDENTIALS_JSON` is set we write its content to a
    tmpfile and point `GOOGLE_APPLICATION_CREDENTIALS` at it. This runs once
    at import time and is a no-op when the file path is already provided.
    """
    json_blob = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
    if not json_blob:
        return
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return  # explicit path wins
    import tempfile

    fd, path = tempfile.mkstemp(prefix="retailsg-firebase-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json_blob)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    logger.info("Materialised GOOGLE_APPLICATION_CREDENTIALS_JSON to %s", path)


def _initialize_firebase() -> firebase_admin.App:
    """Initialize the Firebase Admin SDK (idempotent)."""
    global _app
    if _app is not None:
        return _app

    _materialise_credentials_from_env()

    emulator_host = settings.FIRESTORE_EMULATOR_HOST or os.environ.get(
        "FIRESTORE_EMULATOR_HOST", ""
    )
    if emulator_host:
        os.environ["FIRESTORE_EMULATOR_HOST"] = emulator_host
        logger.info("Using Firestore emulator at %s", emulator_host)

    project_id = settings.FIREBASE_PROJECT_ID or settings.GCP_PROJECT_ID
    try:
        cred = credentials.ApplicationDefault()
        _app = firebase_admin.initialize_app(cred, {"projectId": project_id})
        logger.info("Firebase Admin SDK initialized (project: %s)", project_id)
    except ValueError:
        _app = firebase_admin.get_app()
        logger.info("Firebase Admin SDK already initialized")
    except Exception as exc:
        if _is_auth_error(exc):
            # Fall back to project-ID-only mode so the FastAPI app can boot
            # in environments without ADC (e.g. CI). Any Firestore call will
            # still fail at the network layer with a clear permission error,
            # but the dependency callable itself returns successfully.
            logger.warning(
                "No Firestore credentials available; initializing "
                "firebase-admin in project-ID-only mode (project: %s). "
                "Real Firestore operations will fail.",
                project_id,
            )
            _app = firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            raise

    return _app


def _wrap_db(client: FirestoreClient) -> FirestoreClient:
    """Wrap collection() so the first auth-failure surfaces a friendly hint."""
    original_collection = client.collection

    def collection(*args, **kwargs):
        col = original_collection(*args, **kwargs)
        original_stream = col.stream
        original_get = col.get

        def _guard(call, *a, **kw):
            try:
                result = call(*a, **kw)
                if hasattr(result, "__next__"):
                    return _wrap_iter(result)
                return result
            except Exception as exc:
                if _is_auth_error(exc):
                    print(_AUTH_HINT, file=sys.stderr)
                    raise FirestoreAuthError(str(exc)) from exc
                raise

        def _wrap_iter(it):
            while True:
                try:
                    yield next(it)
                except StopIteration:
                    return
                except Exception as exc:
                    if _is_auth_error(exc):
                        print(_AUTH_HINT, file=sys.stderr)
                        raise FirestoreAuthError(str(exc)) from exc
                    raise

        col.stream = lambda *a, **kw: _guard(original_stream, *a, **kw)
        col.get = lambda *a, **kw: _guard(original_get, *a, **kw)
        return col

    client.collection = collection
    return client


def _get_db() -> FirestoreClient:
    """Initialize Firebase and return the wrapped Firestore client (idempotent)."""
    global _db
    if _db is not None:
        return _db
    _initialize_firebase()
    _db = _wrap_db(firestore.client())
    return _db


def get_firestore_db() -> FirestoreClient:
    """FastAPI dependency that yields the Firestore client."""
    return _get_db()


def __getattr__(name: str):
    # PEP 562: defer `from app.firestore import db` to first access so that
    # importing this module never requires Firebase credentials (allows test
    # collection in environments without GCP ADC).
    if name == "db":
        return _get_db()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
