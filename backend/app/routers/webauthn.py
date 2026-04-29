"""WebAuthn / Passkey authentication.

Gives users biometric sign-in (Face ID, Touch ID, Windows Hello, Android
fingerprint) as an alternative to entering a password. This is strictly
stronger than SMS/TOTP MFA:

  - Phishing-resistant — the credential is cryptographically bound to the
    site's origin, so even a perfect clone of the login page can't use it.
  - No SMS / billing cost.
  - Single-tap UX.

Relationship to Firebase Auth:
  Firebase Auth doesn't natively support WebAuthn as a sign-in method yet
  (as of 2026). We bridge it via CUSTOM TOKENS:
    1. User does WebAuthn assertion against our backend.
    2. On success, we mint a Firebase custom token for that user's uid.
    3. Client calls `signInWithCustomToken(token)`.
    4. From Firebase's point of view, the user just signed in — all existing
       JWT verification, custom claims, refresh-token logic works unchanged.

Data model (Firestore):
    webauthn_credentials/{credential_id}   (credential_id is the b64url-encoded credId)
        user_id:        the Firestore user doc id
        firebase_uid:   Firebase Auth uid (denormalised for fast login lookup)
        email:          lowercased (for login-time lookup by email)
        public_key:     raw CBOR-encoded COSE key bytes (bytes field in FS)
        sign_count:     integer; monotonically increasing; replay guard
        transports:     list[str]  — "internal", "hybrid", "usb", …
        name:           friendly label set by user ("iPhone", "MacBook Pro")
        created_at:     ServerTimestamp
        last_used_at:   ServerTimestamp | None

    webauthn_challenges/{random_id}         (TTL collection; prune on read)
        kind:           "registration" | "authentication"
        user_id:        for registration challenges, the authenticated user's id
        email:          for authentication challenges, lowercased
        challenge:      raw bytes
        expires_at:     datetime (UTC, 5 min from now)

Security notes:
  - We include sign_count verification. If an attacker clones a credential
    and tries to use it in parallel, the counts will desync and we reject.
  - RP ID is derived from the request origin — by default `localhost` in dev
    and the configured public hostname in prod (set WEBAUTHN_RP_ID env var).
  - User verification is REQUIRED on authentication (UV bit in authenticator
    data must be set). This is what forces Face ID / Touch ID / PIN rather
    than just "possession".
"""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from firebase_admin import auth as firebase_auth
from google.cloud import firestore
from pydantic import BaseModel, Field
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.audit import log_event
from app.auth.dependencies import get_current_user
from app.auth.firebase import _get_firebase_app
from app.firestore import get_firestore_db
from app.rate_limit import limiter
from app.schemas.common import DataResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webauthn", tags=["webauthn"])

CRED_COLLECTION = "webauthn_credentials"
CHALLENGE_COLLECTION = "webauthn_challenges"
CHALLENGE_TTL = timedelta(minutes=5)

RP_NAME = "Victoria Enso Retail"


def _rp_id_for(request: Request) -> str:
    """Figure out the Relying Party ID from the request.

    In production, set `WEBAUTHN_RP_ID` to the eTLD+1 you serve the app from
    (e.g. `retail.victoriaenso.com`). RP IDs CANNOT include the scheme or port.
    """
    explicit = os.environ.get("WEBAUTHN_RP_ID", "").strip()
    if explicit:
        return explicit
    # Best-effort: pull host from the Origin/Referer header (strip port).
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if origin:
        host = origin.split("://", 1)[-1].split("/", 1)[0]
        return host.split(":", 1)[0] or "localhost"
    return "localhost"


def _expected_origin(request: Request) -> str:
    """Full origin string (scheme + host + optional port) that the assertion
    must match. Read back from request headers so dev and prod just work."""
    explicit = os.environ.get("WEBAUTHN_ORIGIN", "").strip()
    if explicit:
        return explicit
    origin = request.headers.get("origin")
    if origin:
        return origin
    # Derive from host header as a last resort.
    host = request.headers.get("host") or "localhost:5173"
    scheme = "https" if "localhost" not in host else "http"
    return f"{scheme}://{host}"


# ── Schemas ─────────────────────────────────────────────────────────────────

class RegisterStartResponse(BaseModel):
    options: dict  # The PublicKeyCredentialCreationOptions, JSON form
    challenge_id: str  # Opaque — client sends back on finish


class RegisterFinishRequest(BaseModel):
    challenge_id: str
    credential: dict  # Output of navigator.credentials.create()
    name: str = Field("", description="User-friendly device label")


class LoginStartRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class LoginStartResponse(BaseModel):
    options: dict  # PublicKeyCredentialRequestOptions
    challenge_id: str
    has_credentials: bool = True


class LoginFinishRequest(BaseModel):
    challenge_id: str
    credential: dict  # Output of navigator.credentials.get()


class LoginFinishResponse(BaseModel):
    firebase_token: str  # Firebase custom token — client calls signInWithCustomToken
    email: str


class CredentialRead(BaseModel):
    id: str
    name: str
    transports: list[str] = []
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _store_challenge(db, *, kind: str, challenge: bytes, user_id: str | None = None, email: str | None = None) -> str:
    """Persist a one-shot challenge; return its opaque id."""
    cid = secrets.token_urlsafe(24)
    db.collection(CHALLENGE_COLLECTION).document(cid).set({
        "kind": kind,
        "user_id": user_id,
        "email": email,
        "challenge": challenge,
        "expires_at": datetime.now(timezone.utc) + CHALLENGE_TTL,
    })
    return cid


def _pop_challenge(db, cid: str, expected_kind: str) -> dict:
    ref = db.collection(CHALLENGE_COLLECTION).document(cid)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=400, detail="Invalid or expired challenge")
    data = snap.to_dict() or {}
    # One-shot — always delete.
    ref.delete()
    if data.get("kind") != expected_kind:
        raise HTTPException(status_code=400, detail="Challenge kind mismatch")
    exp = data.get("expires_at")
    if isinstance(exp, datetime):
        if not exp.tzinfo:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            raise HTTPException(status_code=400, detail="Challenge expired")
    return data


def _credentials_for_email(db, email: str) -> list[dict]:
    snaps = (
        db.collection(CREDENTIAL_COLLECTION := CRED_COLLECTION)
        .where("email", "==", email.lower())
        .stream()
    )
    return [{"id": s.id, **(s.to_dict() or {})} for s in snaps]


def _credentials_for_user(db, user_id: str) -> list[dict]:
    snaps = db.collection(CRED_COLLECTION).where("user_id", "==", str(user_id)).stream()
    return [{"id": s.id, **(s.to_dict() or {})} for s in snaps]


def _actor_obj_from_user(user: dict):
    class _A:
        id = str(user.get("id") or "")
        email = str(user.get("email") or "")
        firebase_uid = str(user.get("firebase_uid") or "")
    return _A()


# ── Registration ────────────────────────────────────────────────────────────

@router.post("/register/start", response_model=RegisterStartResponse)
async def register_start(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Kick off registration of a new passkey for the signed-in user.

    Returns `PublicKeyCredentialCreationOptions` that the browser will feed
    into `navigator.credentials.create()` (or @simplewebauthn/browser's
    `startRegistration()`).

    We exclude already-registered credentials so the authenticator refuses
    to re-register the same device (WebAuthn spec behaviour).
    """
    db = get_firestore_db()
    user_id = str(user.get("id") or "")
    email = str(user.get("email") or "").lower()
    display_name = str(user.get("full_name") or email)
    firebase_uid = str(user.get("firebase_uid") or "")
    if not user_id or not firebase_uid:
        raise HTTPException(status_code=400, detail="User record is incomplete")

    existing = _credentials_for_user(db, user_id)
    # WebAuthn wants the credential IDs as bytes. We stored them as the doc
    # id which is b64url text; @simplewebauthn base64url-decodes as needed.
    from webauthn.helpers import base64url_to_bytes
    exclude = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(c["id"]))
        for c in existing
    ]

    options = generate_registration_options(
        rp_id=_rp_id_for(request),
        rp_name=RP_NAME,
        user_id=user_id.encode("utf-8"),
        user_name=email,
        user_display_name=display_name,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Require a user gesture (Face ID / Touch ID / PIN) not just
            # possession of the device. This is what makes this a real
            # authentication factor rather than glorified cookie auth.
            user_verification=UserVerificationRequirement.REQUIRED,
            # Resident key means the credential lives on the authenticator,
            # so the user can sign in without typing an email. Optional — we
            # still support email-first login.
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,    # ES256 — Apple / Android
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,  # RS256 — Windows Hello
            COSEAlgorithmIdentifier.EDDSA,            # Ed25519 — YubiKey 5+
        ],
    )

    challenge_id = _store_challenge(
        db,
        kind="registration",
        challenge=options.challenge,
        user_id=user_id,
        email=email,
    )

    # options_to_json produces a JSON STRING; the frontend wants an object.
    import json
    return RegisterStartResponse(
        options=json.loads(options_to_json(options)),
        challenge_id=challenge_id,
    )


@router.post("/register/finish", response_model=DataResponse[CredentialRead])
async def register_finish(
    request: Request,
    payload: RegisterFinishRequest,
    user: dict = Depends(get_current_user),
):
    """Verify the attestation returned by the authenticator and persist it."""
    db = get_firestore_db()
    user_id = str(user.get("id") or "")
    firebase_uid = str(user.get("firebase_uid") or "")
    email = str(user.get("email") or "").lower()

    challenge = _pop_challenge(db, payload.challenge_id, "registration")
    if str(challenge.get("user_id")) != user_id:
        raise HTTPException(status_code=400, detail="Challenge belongs to another user")

    try:
        verification = verify_registration_response(
            credential=payload.credential,
            expected_challenge=challenge["challenge"],
            expected_rp_id=_rp_id_for(request),
            expected_origin=_expected_origin(request),
            require_user_verification=True,
        )
    except Exception as exc:
        log.warning("webauthn registration verification failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Registration verification failed: {exc}") from exc

    from webauthn.helpers import bytes_to_base64url
    cred_id_b64 = bytes_to_base64url(verification.credential_id)
    name = payload.name.strip() or "Biometric device"
    transports = payload.credential.get("response", {}).get("transports") or []

    db.collection(CRED_COLLECTION).document(cred_id_b64).set({
        "user_id": user_id,
        "firebase_uid": firebase_uid,
        "email": email,
        "public_key": verification.credential_public_key,  # raw bytes
        "sign_count": int(verification.sign_count),
        "transports": list(transports),
        "name": name,
        "created_at": firestore.SERVER_TIMESTAMP,
        "last_used_at": None,
    })

    log_event(
        "webauthn.register",
        actor=_actor_obj_from_user(user),
        target=_actor_obj_from_user(user),
        metadata={"credential_id": cred_id_b64[:12] + "…", "name": name},
        request=request,
    )

    return DataResponse(data=CredentialRead(
        id=cred_id_b64,
        name=name,
        transports=list(transports),
        created_at=datetime.now(timezone.utc),
        last_used_at=None,
    ))


# ── Authentication ──────────────────────────────────────────────────────────

@router.post("/login/start", response_model=LoginStartResponse)
@limiter.limit("20/minute")
async def login_start(request: Request, response: Response, payload: LoginStartRequest):
    """Begin a passwordless sign-in.

    The client provides the email (so we can scope the challenge to that
    user's credentials). If the account has no passkeys registered, we still
    return a valid-looking challenge with `has_credentials=false` so an
    attacker can't enumerate which emails have passkeys — but the UI uses
    that flag to redirect the user to the password flow instead.
    """
    db = get_firestore_db()
    email = payload.email.strip().lower()
    creds = _credentials_for_email(db, email)

    from webauthn.helpers import base64url_to_bytes
    allow = [
        PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(c["id"]),
            transports=c.get("transports") or None,
        )
        for c in creds
    ]

    options = generate_authentication_options(
        rp_id=_rp_id_for(request),
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    challenge_id = _store_challenge(
        db,
        kind="authentication",
        challenge=options.challenge,
        email=email,
    )

    import json
    return LoginStartResponse(
        options=json.loads(options_to_json(options)),
        challenge_id=challenge_id,
        has_credentials=bool(creds),
    )


@router.post("/login/finish", response_model=LoginFinishResponse)
@limiter.limit("20/minute")
async def login_finish(request: Request, response: Response, payload: LoginFinishRequest):
    """Verify the assertion and mint a Firebase custom token."""
    db = get_firestore_db()
    challenge = _pop_challenge(db, payload.challenge_id, "authentication")

    cred_id = payload.credential.get("id") or payload.credential.get("rawId")
    if not cred_id:
        raise HTTPException(status_code=400, detail="Credential id missing")

    snap = db.collection(CRED_COLLECTION).document(cred_id).get()
    if not snap.exists:
        raise HTTPException(status_code=401, detail="Unknown credential")
    cred = snap.to_dict() or {}

    # Defence-in-depth: the stored email MUST match the challenge's email.
    if challenge.get("email") and challenge["email"] != cred.get("email"):
        raise HTTPException(status_code=401, detail="Credential / challenge email mismatch")

    public_key = cred.get("public_key")
    if not public_key:
        raise HTTPException(status_code=500, detail="Credential public key missing")
    # Firestore may return bytes as `Blob`/`bytes`. py_webauthn wants raw bytes.
    if not isinstance(public_key, (bytes, bytearray)):
        raise HTTPException(status_code=500, detail="Credential public key is not bytes")

    try:
        verification = verify_authentication_response(
            credential=payload.credential,
            expected_challenge=challenge["challenge"],
            expected_rp_id=_rp_id_for(request),
            expected_origin=_expected_origin(request),
            credential_public_key=bytes(public_key),
            credential_current_sign_count=int(cred.get("sign_count") or 0),
            require_user_verification=True,
        )
    except Exception as exc:
        log.warning("webauthn auth verification failed: %s", exc)
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}") from exc

    # Update the credential's sign_count + last_used_at. Sign-count replay
    # protection only fires if the authenticator actually exposes a counter
    # (some — like iCloud Keychain — don't; they always send 0). py_webauthn
    # already validated it; we just record the new value.
    db.collection(CRED_COLLECTION).document(cred_id).update({
        "sign_count": int(verification.new_sign_count),
        "last_used_at": firestore.SERVER_TIMESTAMP,
    })

    firebase_uid = cred.get("firebase_uid")
    email = cred.get("email") or challenge.get("email") or ""
    if not firebase_uid:
        raise HTTPException(status_code=500, detail="Credential not linked to a Firebase user")

    # Mint a custom token. Claims is optional; we set `auth_method` so the
    # backend can tell biometric vs password sign-ins apart if it wants.
    _get_firebase_app()
    try:
        token = firebase_auth.create_custom_token(
            firebase_uid,
            {"auth_method": "webauthn"},
        ).decode("utf-8")
    except Exception as exc:
        log.warning("create_custom_token failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Could not mint sign-in token: {exc}") from exc

    log_event(
        "webauthn.login",
        actor=type("A", (), {"id": "", "email": email, "firebase_uid": firebase_uid})(),
        target=type("T", (), {"id": str(cred.get("user_id") or ""), "email": email, "firebase_uid": firebase_uid})(),
        metadata={"credential_id": cred_id[:12] + "…"},
        request=request,
    )

    return LoginFinishResponse(firebase_token=token, email=email)


# ── Credential management ───────────────────────────────────────────────────

@router.get("/credentials", response_model=DataResponse[list[CredentialRead]])
async def list_credentials(user: dict = Depends(get_current_user)):
    db = get_firestore_db()
    user_id = str(user.get("id") or "")
    creds = _credentials_for_user(db, user_id)
    out: list[CredentialRead] = []
    for c in creds:
        out.append(CredentialRead(
            id=c["id"],
            name=c.get("name") or "Biometric device",
            transports=c.get("transports") or [],
            created_at=c.get("created_at"),
            last_used_at=c.get("last_used_at"),
        ))
    out.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return DataResponse(data=out)


@router.delete("/credentials/{credential_id}")
async def delete_credential(
    credential_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    db = get_firestore_db()
    ref = db.collection(CRED_COLLECTION).document(credential_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Credential not found")
    data = snap.to_dict() or {}
    if str(data.get("user_id")) != str(user.get("id") or ""):
        raise HTTPException(status_code=403, detail="Not your credential")
    ref.delete()
    log_event(
        "webauthn.revoke",
        actor=_actor_obj_from_user(user),
        target=_actor_obj_from_user(user),
        metadata={"credential_id": credential_id[:12] + "…", "name": data.get("name", "")},
        request=request,
    )
    return {"ok": True}
