"""Root pytest configuration shared by tests/ and unit_tests/.

When run in environments without Firestore credentials (e.g. CI without
GOOGLE_APPLICATION_CREDENTIALS), the real `get_firestore_db` dependency
cannot be invoked because `firestore.client()` requires Application Default
Credentials. The unit-test suites already monkeypatch the
`firestore_helpers` functions, so the dependency value itself is never
read; we just need the callable to return without raising. This is achieved
by replacing `app.firestore._get_db` with a stub that returns ``None`` and
by registering a global FastAPI dependency override for any app instance
that imports `app.main.app`.
"""
from __future__ import annotations

import os
from pathlib import Path


def _has_firestore_credentials() -> bool:
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON"):
        return True
    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        return True
    well_known = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return well_known.exists()


if not _has_firestore_credentials():
    import app.firestore as _fs

    def _stub_get_db():
        return None

    _fs._get_db = _stub_get_db  # type: ignore[assignment]
