"""Mint a fresh Firebase ID token for the dedicated E2E test user.

Usage:
  # Print a token to stdout (most common)
  python tools/scripts/dev_get_id_token.py

  # Use it inline with curl
  curl -H "Authorization: Bearer $(python tools/scripts/dev_get_id_token.py)" \
       http://localhost:8000/api/supplier-review/CN-001/orders

How it works
------------
1. Reads ``apps/staff-portal/.env.e2e`` to learn the test user's email
   (only used to look up the Firebase UID; password is not used here).
   Re-run ``tools/scripts/seed_e2e_test_user.py --apply`` if the file is
   missing.
2. Uses the Firebase Admin SDK (via Application Default Credentials,
   typically ``gcloud auth application-default login``) to mint a
   *custom token* for that UID. This sidesteps Email/Password provider
   configuration entirely — we only need the project's UID.
3. Exchanges the custom token for an ID token via Identity Toolkit's
   ``accounts:signInWithCustomToken`` REST endpoint and prints the
   ``idToken`` to stdout.

Firebase Web API key resolution order:
  a. ``$RETAILSG_FIREBASE_WEB_API_KEY`` env var
  b. ``$VITE_FIREBASE_API_KEY`` env var
  c. ``$XDG_CONFIG_HOME/retailsg/firebase_web_api_key``
     (defaults to ``~/.config/retailsg/firebase_web_api_key``)
  d. Interactive prompt — saves the answer to the config path at 0600.

The Firebase Web API key is *not* a secret per se — it's bundled in every
client JS app — but we keep it outside the repo so it doesn't leak into
git history or CI logs.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from getpass import getpass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_E2E = REPO_ROOT / "apps" / "staff-portal" / ".env.e2e"

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
KEY_FILE = CONFIG_HOME / "retailsg" / "firebase_web_api_key"

IDENTITY_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "victoriaensoapp")


def _die(msg: str, code: int = 2) -> None:
    print(f"dev_get_id_token: {msg}", file=sys.stderr)
    sys.exit(code)


def _read_test_email() -> str:
    if not ENV_E2E.is_file():
        _die(
            f"missing {ENV_E2E}. Run:\n"
            f"  python tools/scripts/seed_e2e_test_user.py --apply"
        )
    for raw in ENV_E2E.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k == "TEST_EMAIL":
            return v
    _die(f"{ENV_E2E} is missing TEST_EMAIL")
    return ""  # unreachable


def _read_api_key() -> str:
    for var in ("RETAILSG_FIREBASE_WEB_API_KEY", "VITE_FIREBASE_API_KEY"):
        v = os.environ.get(var, "").strip()
        if v:
            return v
    if KEY_FILE.is_file():
        v = KEY_FILE.read_text().strip()
        if v:
            return v
    if not sys.stdin.isatty():
        _die(
            "no Firebase Web API key found and stdin is not a TTY.\n"
            "Set $RETAILSG_FIREBASE_WEB_API_KEY or write the key to "
            f"{KEY_FILE}."
        )
    print(
        f"No Firebase Web API key found at {KEY_FILE}.\n"
        "Find it in Firebase Console → Project settings → General → "
        "'Web API Key' (or 'apiKey' in the snippet under 'Your apps').\n",
        file=sys.stderr,
    )
    key = getpass("Paste Firebase Web API key (input hidden): ").strip()
    if not key:
        _die("empty key — aborting")
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key + "\n")
    KEY_FILE.chmod(0o600)
    print(f"Saved key to {KEY_FILE} (0600).", file=sys.stderr)
    return key


def _mint_custom_token(email: str) -> str:
    """Use the Admin SDK to look up the test user's UID and mint a custom token."""
    try:
        import firebase_admin  # type: ignore
        from firebase_admin import auth as fb_auth  # type: ignore
    except ImportError:
        _die(
            "firebase_admin is not installed. Activate the backend venv first, e.g.:\n"
            "  source backend/.venv/bin/activate"
        )
    if not firebase_admin._apps:
        try:
            firebase_admin.initialize_app(options={"projectId": PROJECT_ID})
        except Exception as exc:  # noqa: BLE001
            _die(f"firebase_admin.initialize_app failed: {exc}")
    try:
        record = fb_auth.get_user_by_email(email)
    except fb_auth.UserNotFoundError:
        _die(
            f"no Firebase user for {email}. Run:\n"
            f"  python tools/scripts/seed_e2e_test_user.py --apply"
        )
    try:
        return fb_auth.create_custom_token(record.uid).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        _die(
            f"create_custom_token failed: {exc}\n"
            "If you see 'serviceAccountId' / 'iam.serviceAccounts.signBlob' errors,\n"
            "either run `gcloud auth application-default login` against an account\n"
            "with the 'Service Account Token Creator' role, or point\n"
            "GOOGLE_APPLICATION_CREDENTIALS at a service-account JSON file."
        )


def _exchange_custom_token(custom_token: str, api_key: str) -> str:
    body = json.dumps(
        {"token": custom_token, "returnSecureToken": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{IDENTITY_URL}?key={api_key}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8")).get("error", {})
        except Exception:
            err = {}
        msg = err.get("message", str(exc))
        _die(f"signInWithCustomToken failed ({exc.code}): {msg}")
    except urllib.error.URLError as exc:
        _die(f"network error reaching Identity Toolkit: {exc}")
    token = payload.get("idToken")
    if not token:
        _die(f"unexpected response: {payload!r}")
    return token


def main() -> None:
    email = _read_test_email()
    key = _read_api_key()
    custom = _mint_custom_token(email)
    token = _exchange_custom_token(custom, key)
    sys.stdout.write(token)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
