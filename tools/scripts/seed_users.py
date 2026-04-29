#!/usr/bin/env python3
"""
Provision launch user accounts.

Creates/updates Firebase Auth users, their Firestore ``users`` docs, and
per-store roles under ``stores/{store_id}/roles/{user_id}``. Works against
the GCP project associated with Application Default Credentials.

Run this on a machine where ``gcloud auth application-default login`` has
been configured.

Usage:
  # Dry-run (default) — shows what would happen, no writes
  python seed_users.py

  # Apply changes — generates random passwords and prints them ONCE
  python seed_users.py --apply

  # Reset a single user's password (prints the new one)
  python seed_users.py --apply --only craig@victoriaenso.com --reset-password
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import auth, firestore


PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "victoriaensoapp")


# ── Roster ───────────────────────────────────────────────────────────────────
# ``stores = ["ALL"]`` grants the role at every store that exists in Firestore.
# Otherwise list specific ``store_code`` values.
ROSTER: list[dict[str, Any]] = [
    {
        "email": "craig@victoriaenso.com",
        "display_name": "Craig",
        "role":  "owner",
        "stores": ["ALL"],
    },
    {
        "email": "irina@victoriaenso.com",
        "display_name": "Irina",
        "role":  "owner",
        "stores": ["ALL"],
    },
    {
        "email": "gladis@victoriaenso.com",
        "display_name": "Gladis",
        "role":  "manager",
        "stores": ["TAKA-01"],
    },
    {
        "email": "michelle@victoriaenso.com",
        "display_name": "Michelle",
        "role":  "manager",
        "stores": ["ISETAN-01"],
    },
    # Staff roster — appears in Taka + Isetan payroll columns through 2025/2026.
    # Store assignments are a best-guess; managers can refine via /admin/users.
    {
        "email": "evonne@victoriaenso.com",
        "display_name": "Evonne",
        "role":  "staff",
        "stores": ["TAKA-01", "ISETAN-01"],
    },
    {
        "email": "rinku@victoriaenso.com",
        "display_name": "Rinku",
        "role":  "staff",
        "stores": ["TAKA-01", "ISETAN-01"],
    },
    {
        "email": "jillian@victoriaenso.com",
        "display_name": "Jillian",
        "role":  "staff",
        "stores": ["TAKA-01", "ISETAN-01"],
    },
    {
        "email": "olly@victoriaenso.com",
        "display_name": "Olly",
        "role":  "staff",
        "stores": ["TAKA-01", "ISETAN-01"],
    },
    {
        "email": "soniya@victoriaenso.com",
        "display_name": "Soniya",
        "role":  "staff",
        "stores": ["TAKA-01", "ISETAN-01"],
    },
    {
        "email": "shiela@victoriaenso.com",
        "display_name": "Shiela",
        "role":  "staff",
        "stores": ["TAKA-01", "ISETAN-01"],
    },
    {
        "email": "oliver@victoriaenso.com",
        "display_name": "Oliver",
        "role":  "staff",
        "stores": ["TAKA-01", "ISETAN-01"],
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

_PW_ALPHABET = string.ascii_letters + string.digits


def generate_password(length: int = 14) -> str:
    """14 chars of letters+digits — ~83 bits entropy; easy to copy; no shell-special chars."""
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def init_firebase() -> None:
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": PROJECT_ID})


def ensure_auth_user(
    email: str,
    display_name: str,
    password: str | None,
    *,
    reset_password: bool,
) -> tuple[str, str | None]:
    """Return (uid, password_if_set). ``password_if_set`` is None when we
    left the existing password alone."""
    try:
        user = auth.get_user_by_email(email)
        if reset_password:
            pw = password or generate_password()
            auth.update_user(user.uid, password=pw, email_verified=True, display_name=display_name)
            return user.uid, pw
        # Existing user, no reset — keep password as-is
        if display_name and user.display_name != display_name:
            auth.update_user(user.uid, display_name=display_name)
        return user.uid, None
    except auth.UserNotFoundError:
        pw = password or generate_password()
        user = auth.create_user(
            email=email,
            password=pw,
            display_name=display_name,
            email_verified=True,
        )
        return user.uid, pw


def ensure_firestore_user(db, firebase_uid: str, email: str, display_name: str) -> str:
    """Upsert the users/{id} doc keyed by firebase_uid. Returns user_id."""
    existing = list(
        db.collection("users").where("firebase_uid", "==", firebase_uid).limit(1).stream()
    )
    now = datetime.now(timezone.utc)
    if existing:
        doc = existing[0]
        user_id = doc.id
        db.collection("users").document(user_id).set(
            {
                "firebase_uid": firebase_uid,
                "email": email,
                "full_name": display_name,
                "updated_at": now,
            },
            merge=True,
        )
        return user_id

    user_id = str(uuid.uuid4())
    db.collection("users").document(user_id).set({
        "id": user_id,
        "firebase_uid": firebase_uid,
        "email": email,
        "full_name": display_name,
        "phone": None,
        "created_at": now,
        "updated_at": now,
    })
    return user_id


def resolve_stores(db, store_codes: list[str]) -> list[tuple[str, str]]:
    """Map store_codes (or ['ALL']) to [(store_id, store_code), ...]."""
    wants_all = any(c.upper() == "ALL" for c in store_codes)
    if wants_all:
        all_stores = db.collection("stores").stream()
        return [(doc.id, (doc.to_dict() or {}).get("store_code", doc.id)) for doc in all_stores]

    out = []
    for code in store_codes:
        matches = list(
            db.collection("stores").where("store_code", "==", code).limit(1).stream()
        )
        if not matches:
            print(f"   WARNING  store_code '{code}' not found in Firestore")
            continue
        out.append((matches[0].id, code))
    return out


def ensure_role(db, store_id: str, user_id: str, role: str) -> str:
    """Upsert stores/{store_id}/roles/{user_id}. Returns 'created'|'updated'|'unchanged'."""
    role_ref = db.collection("stores").document(store_id).collection("roles").document(user_id)
    existing = role_ref.get()
    now = datetime.now(timezone.utc)
    if existing.exists:
        ed = existing.to_dict() or {}
        if ed.get("role") == role:
            return "unchanged"
        role_ref.set({"role": role, "updated_at": now}, merge=True)
        return "updated"
    role_ref.set({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "store_id": store_id,
        "role": role,
        "created_at": now,
    })
    return "created"


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually provision. Default is dry-run.")
    parser.add_argument("--only", action="append", default=[], help="Restrict to specific emails. Repeat for multiple.")
    parser.add_argument("--reset-password", action="store_true", help="Force a new password for existing users.")
    parser.add_argument(
        "--credentials-out",
        metavar="PATH",
        default=None,
        help=(
            "Write new credentials to a JSON file at 0600 permissions instead of printing "
            "them to stdout. Strongly recommended for any non-local run so passwords don't "
            "leak into terminal scrollback, shell history, or CI logs."
        ),
    )
    args = parser.parse_args()

    roster = ROSTER
    if args.only:
        wanted = set(e.strip().lower() for e in args.only)
        roster = [r for r in roster if r["email"].lower() in wanted]
        if not roster:
            print(f"No roster entries matched --only {args.only}")
            return

    if not args.apply:
        print("DRY RUN — no changes will be made. Re-run with --apply to provision.\n")

    init_firebase()
    db = firestore.client()

    # Print the plan
    print(f"{'email':32s}  {'name':12s}  {'role':9s}  stores")
    print("-" * 90)
    for r in roster:
        print(f"{r['email']:32s}  {r['display_name']:12s}  {r['role']:9s}  {', '.join(r['stores'])}")
    print()

    if not args.apply:
        return

    # Apply
    credentials_to_print: list[tuple[str, str]] = []
    for r in roster:
        email = r["email"]
        display_name = r["display_name"]
        role = r["role"]

        print(f"\n▶ {email}")
        uid, new_password = ensure_auth_user(
            email=email,
            display_name=display_name,
            password=None,
            reset_password=args.reset_password,
        )
        print(f"   auth uid     : {uid}")
        if new_password:
            credentials_to_print.append((email, new_password))
            print(f"   password set : (captured — will print at end)")
        else:
            print(f"   password     : (unchanged)")

        user_id = ensure_firestore_user(db, uid, email, display_name)
        print(f"   firestore id : {user_id}")

        stores = resolve_stores(db, r["stores"])
        print(f"   stores       : {len(stores)}")
        for sid, scode in stores:
            status = ensure_role(db, sid, user_id, role)
            print(f"     {scode:12s}  {role:9s}  [{status}]")

    # Credentials output
    if not credentials_to_print:
        print("\n(no new passwords were set)")
    elif args.credentials_out:
        out_path = Path(args.credentials_out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": (
                "Share each password via 1Password / Signal, then delete this file. "
                "Passwords were generated with secrets.choice and never touched stdout."
            ),
            "credentials": [
                {"email": email, "password": pw} for email, pw in credentials_to_print
            ],
        }
        # Write with explicit 0600 perms. Use os.open so the mode is applied
        # atomically — plain open() can race where another process sees the
        # default-permission file before we chmod it.
        fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\n✓ Wrote {len(credentials_to_print)} credentials to {out_path} (mode 0600)")
        print("  Share each via 1Password / Signal, then `shred -u` the file.")
    else:
        print("\n" + "=" * 60)
        print(" CREDENTIALS (store these securely — shown only once)")
        print(" ⚠ These ended up in your terminal scrollback. Next time use")
        print("    --credentials-out <path> to write them to a 0600 file instead.")
        print("=" * 60)
        for email, pw in credentials_to_print:
            print(f"  {email:32s}  {pw}")
        print("=" * 60)
    print("\nAll users have `email_verified=true`. Share passwords via 1Password / Signal / similar.")


if __name__ == "__main__":
    main()
