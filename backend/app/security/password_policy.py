"""Password policy helpers.

Implements the NIST 800-63B guidance we can realistically enforce for a small
retail team:
- Minimum length (8 per NIST; we use 10 for a little extra headroom)
- Maximum length (64; Firebase Auth already caps around 4096 but we reject early)
- No whitespace padding / null bytes
- Breach check against HaveIBeenPwned's k-anonymity API
  (https://haveibeenpwned.com/API/v3#PwnedPasswords) — we send only the first
  five SHA-1 hex chars and grep the returned list locally, so the plaintext
  never leaves the server.

The HIBP check is network-dependent; when offline we fail-open (log a warning
and allow) because blocking all password changes during an internet outage is
worse than the marginal risk of one weak password slipping through. If stricter
enforcement is needed later, flip `_FAIL_OPEN` to False.
"""
from __future__ import annotations

import hashlib
import logging

import httpx

log = logging.getLogger(__name__)

MIN_LEN = 10
MAX_LEN = 64
_HIBP_URL = "https://api.pwnedpasswords.com/range/{prefix}"
_HIBP_TIMEOUT = 3.0  # seconds — intentionally short; we fail-open on timeout
_FAIL_OPEN = True


class PasswordPolicyError(ValueError):
    """Raised when a candidate password violates policy. The message is safe to
    surface directly to the end user."""


def _basic_checks(password: str) -> None:
    if not isinstance(password, str):
        raise PasswordPolicyError("Password must be a string")
    if len(password) < MIN_LEN:
        raise PasswordPolicyError(f"Password must be at least {MIN_LEN} characters")
    if len(password) > MAX_LEN:
        raise PasswordPolicyError(f"Password must be at most {MAX_LEN} characters")
    if password != password.strip():
        raise PasswordPolicyError("Password cannot start or end with whitespace")
    if "\x00" in password:
        raise PasswordPolicyError("Password cannot contain null bytes")


def pwned_count(password: str) -> int:
    """Return how many times this password appears in HIBP's breach corpus.

    Uses the k-anonymity model: we hash the password with SHA-1, send only the
    first 5 hex chars ("prefix"), and match the "suffix" locally against the
    returned list. HIBP never sees the password or its full hash.

    Returns 0 on any network/HTTP error when `_FAIL_OPEN` is True.
    """
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324 — SHA-1 here is per HIBP spec, not for auth
    prefix, suffix = sha1[:5], sha1[5:]
    try:
        resp = httpx.get(
            _HIBP_URL.format(prefix=prefix),
            headers={"User-Agent": "retailsg-password-policy"},
            timeout=_HIBP_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        if _FAIL_OPEN:
            log.warning("HIBP check failed (fail-open): %s", exc)
            return 0
        raise PasswordPolicyError("Could not verify password safety, please try again") from exc

    for line in resp.text.splitlines():
        try:
            hsuf, count = line.strip().split(":")
        except ValueError:
            continue
        if hsuf.upper() == suffix:
            try:
                return int(count)
            except ValueError:
                return 1
    return 0


def enforce(password: str) -> None:
    """Run all checks; raise `PasswordPolicyError` with a user-safe message on failure."""
    _basic_checks(password)
    hits = pwned_count(password)
    if hits > 0:
        # Wording taken from NIST 800-63B §5.1.1.2 guidance.
        raise PasswordPolicyError(
            "This password has appeared in a known data breach "
            f"({hits:,} times) and cannot be used. Please choose a different one."
        )
