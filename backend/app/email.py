"""Transactional email dispatch.

Pluggable backend — the real provider (SendGrid / SES / Postmark / whatever)
is swapped via environment, not code. Until a provider is wired in, we use
the `ConsoleBackend` which logs every message to stdout with enough detail
that you can eyeball the delivery flow during dev / staging. Templates
rendered here are intentionally plain-text so they're trivially reviewable
in an audit.

Activation:
    Set SENDGRID_API_KEY in the environment to switch to the SendGrid HTTP
    backend. Leave it unset and you get ConsoleBackend (safe for local).

All public helpers are fire-and-forget — they never raise. A dead email
provider must NEVER roll back a password change or role grant; the audit log
is the authoritative record.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger(__name__)

DEFAULT_FROM = os.environ.get(
    "NOTIF_FROM_EMAIL",
    "no-reply@victoriaenso.com",
)
DEFAULT_FROM_NAME = os.environ.get("NOTIF_FROM_NAME", "Victoria Enso Retail")


# ── Backends ────────────────────────────────────────────────────────────────

@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str


class _Backend:
    def send(self, msg: EmailMessage) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleBackend(_Backend):
    """Writes the message to the application log. Useful for dev, CI,
    and any environment where we don't yet want to pay for a real provider."""

    def send(self, msg: EmailMessage) -> None:
        log.info(
            "EMAIL (console backend) → %s | subject=%r\n%s",
            msg.to, msg.subject, msg.body,
        )


class SendGridBackend(_Backend):
    """Minimal SendGrid v3 HTTP client. Installed-package-free — just uses
    httpx which is already in requirements.txt."""

    _ENDPOINT = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def send(self, msg: EmailMessage) -> None:
        payload = {
            "personalizations": [{"to": [{"email": msg.to}]}],
            "from": {"email": DEFAULT_FROM, "name": DEFAULT_FROM_NAME},
            "subject": msg.subject,
            "content": [{"type": "text/plain", "value": msg.body}],
        }
        try:
            r = httpx.post(
                self._ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=5.0,
            )
            if r.status_code >= 300:
                log.warning("SendGrid rejected email to %s: %s %s", msg.to, r.status_code, r.text[:200])
        except Exception as exc:  # noqa: BLE001 — email is fire-and-forget
            log.warning("SendGrid delivery failed for %s: %s", msg.to, exc)


def _pick_backend() -> _Backend:
    key = os.environ.get("SENDGRID_API_KEY", "").strip()
    if key:
        return SendGridBackend(key)
    return ConsoleBackend()


_backend = _pick_backend()


def _send(msg: EmailMessage) -> None:
    try:
        _backend.send(msg)
    except Exception as exc:  # noqa: BLE001
        log.warning("Email backend raised for %s: %s", msg.to, exc)


# ── Templates ───────────────────────────────────────────────────────────────

_SIGNATURE = "\n\n—\nVictoria Enso Retail\nIf this wasn't you, contact an owner immediately."


def send_password_changed_self(*, to: str, display_name: Optional[str], ip: Optional[str], user_agent: Optional[str]) -> None:
    """Notify a user that THEY just rotated their own password."""
    who = display_name or to
    body = (
        f"Hi {who},\n\n"
        "Your Victoria Enso Retail password was just changed using your current sign-in.\n"
    )
    if ip or user_agent:
        body += f"\nWhere: {ip or 'unknown IP'} — {user_agent or 'unknown device'}\n"
    body += (
        "\nAll other signed-in devices have been signed out as a safety measure.\n"
        "If this wasn't you, ask an owner to reset your account and investigate."
    )
    _send(EmailMessage(to=to, subject="Your password was changed", body=body + _SIGNATURE))


def send_password_reset_by_admin(*, to: str, display_name: Optional[str], admin_email: str, reset_link: str) -> None:
    """Notify a user that an admin rotated their password and generated a reset link."""
    who = display_name or to
    body = (
        f"Hi {who},\n\n"
        f"A Victoria Enso Retail administrator ({admin_email}) has reset your account "
        "password and generated a one-time sign-in link for you:\n\n"
        f"  {reset_link}\n\n"
        "The link expires in about 1 hour and can be used only once.\n"
        "After signing in you'll be asked to pick a new password.\n\n"
        "Your existing sessions on other devices have been signed out.\n"
        "If you didn't expect this, contact the admin or another owner immediately."
    )
    _send(EmailMessage(to=to, subject="Your password was reset by an administrator", body=body + _SIGNATURE))


def send_invite(*, to: str, display_name: Optional[str], inviter_email: str, setup_link: str, role: str, stores: list[str]) -> None:
    """Welcome email for a newly invited user containing their one-time
    password-setup link."""
    who = display_name or to.split("@")[0]
    store_line = ", ".join(stores) if stores else "(no stores assigned yet)"
    body = (
        f"Hi {who},\n\n"
        f"{inviter_email} has invited you to the Victoria Enso Retail staff portal as a {role}.\n"
        f"Stores: {store_line}\n\n"
        "Click the link below to pick your password and sign in for the first time:\n\n"
        f"  {setup_link}\n\n"
        "The link expires in about 1 hour and can only be used once. If it expires before you "
        "get to it, ask your manager to resend the invite.\n"
    )
    _send(EmailMessage(to=to, subject="You've been invited to Victoria Enso Retail", body=body + _SIGNATURE))


def send_new_device_signin(*, to: str, display_name: Optional[str], ip: Optional[str], user_agent: Optional[str], when: str) -> None:
    """Notify a user that we saw a sign-in from a device/IP they hadn't used before."""
    who = display_name or to
    body = (
        f"Hi {who},\n\n"
        "We noticed a sign-in to your Victoria Enso Retail account from a device we haven't seen before.\n\n"
        f"When:   {when}\n"
        f"Where:  {ip or 'unknown IP'}\n"
        f"Device: {user_agent or 'unknown device'}\n\n"
        "If that was you, you can ignore this email.\n"
        "If not, change your password right away and tell an owner."
    )
    _send(EmailMessage(to=to, subject="New sign-in to your account", body=body + _SIGNATURE))
