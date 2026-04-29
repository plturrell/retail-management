"""Tests for ``require_scheduler_oidc`` — Cloud Scheduler OIDC gate.

Patches ``google.oauth2.id_token.verify_oauth2_token`` so we never hit the
network for Google's JWKS. Verifies the four rejection paths (missing token,
invalid token, unverified email, wrong service account) and the happy path.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import dependencies as deps
from app.config import settings


@pytest.fixture(autouse=True)
def _scheduler_settings(monkeypatch):
    monkeypatch.setattr(settings, "CAG_SCHEDULER_SA_EMAIL", "cag-scheduler@victoriaenso.iam.gserviceaccount.com")
    monkeypatch.setattr(settings, "CAG_SCHEDULER_AUDIENCE", "https://retailsg-api-victoriaenso.run.app")
    yield


def _patch_verify(monkeypatch, claims):
    def _fake(token, request, audience=None):
        return claims
    monkeypatch.setattr(deps.id_token, "verify_oauth2_token", _fake)


def test_rejects_missing_authorization_header():
    with pytest.raises(HTTPException) as exc:
        deps.require_scheduler_oidc(authorization=None)
    assert exc.value.status_code == 401


def test_rejects_non_bearer_scheme():
    with pytest.raises(HTTPException) as exc:
        deps.require_scheduler_oidc(authorization="Basic abc")
    assert exc.value.status_code == 401


def test_rejects_invalid_token(monkeypatch):
    def _raise(token, request, audience=None):
        raise ValueError("bad signature")
    monkeypatch.setattr(deps.id_token, "verify_oauth2_token", _raise)
    with pytest.raises(HTTPException) as exc:
        deps.require_scheduler_oidc(authorization="Bearer fake.jwt.value")
    assert exc.value.status_code == 401
    assert "invalid oidc" in exc.value.detail.lower()


def test_rejects_unverified_email(monkeypatch):
    _patch_verify(monkeypatch, {
        "email": "cag-scheduler@victoriaenso.iam.gserviceaccount.com",
        "email_verified": False,
        "sub": "123",
    })
    with pytest.raises(HTTPException) as exc:
        deps.require_scheduler_oidc(authorization="Bearer fake.jwt.value")
    assert exc.value.status_code == 403
    assert "email not verified" in exc.value.detail.lower()


def test_rejects_wrong_service_account(monkeypatch):
    _patch_verify(monkeypatch, {
        "email": "intern@victoriaenso.iam.gserviceaccount.com",
        "email_verified": True,
        "sub": "123",
    })
    with pytest.raises(HTTPException) as exc:
        deps.require_scheduler_oidc(authorization="Bearer fake.jwt.value")
    assert exc.value.status_code == 403
    assert "wrong service account" in exc.value.detail.lower()


def test_accepts_correct_oidc_token(monkeypatch):
    _patch_verify(monkeypatch, {
        "email": "cag-scheduler@victoriaenso.iam.gserviceaccount.com",
        "email_verified": True,
        "sub": "987654321",
    })
    out = deps.require_scheduler_oidc(authorization="Bearer fake.jwt.value")
    assert out["email"] == "cag-scheduler@victoriaenso.iam.gserviceaccount.com"
    assert out["sub"] == "987654321"
