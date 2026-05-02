import os
import json

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import HTTPException, status

from app.config import settings

# Initialize Firebase Admin SDK.
# Priority:
#   1. GOOGLE_APPLICATION_CREDENTIALS env var → service account JSON file
#   2. GCP Application Default Credentials (gcloud auth application-default login)
#   3. Fallback to project-ID-only init (sufficient for token verification)
#
# Note: GCP org policy may block service account key creation.
# In that case, use ADC locally or Workload Identity on Cloud Run.
_firebase_app = None


def _get_firebase_app():
    global _firebase_app
    if _firebase_app is None:
        try:
            _firebase_app = firebase_admin.get_app()
        except ValueError:
            cred_path = settings.GOOGLE_APPLICATION_CREDENTIALS or os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS", ""
            )
            if cred_path and os.path.isfile(cred_path):
                # A service-account JSON can be loaded as a certificate. A
                # local gcloud ADC JSON is an `authorized_user` file and must
                # go through ApplicationDefault instead.
                with open(cred_path, encoding="utf-8") as fh:
                    cred_type = json.load(fh).get("type")
                if cred_type == "service_account":
                    cred = credentials.Certificate(cred_path)
                else:
                    cred = credentials.ApplicationDefault()
                _firebase_app = firebase_admin.initialize_app(
                    cred,
                    options={"projectId": settings.FIREBASE_PROJECT_ID},
                )
            else:
                try:
                    # Try Application Default Credentials (works on GCP and
                    # locally after `gcloud auth application-default login`)
                    cred = credentials.ApplicationDefault()
                    _firebase_app = firebase_admin.initialize_app(
                        cred, options={"projectId": settings.FIREBASE_PROJECT_ID}
                    )
                except Exception:
                    # Last resort: project-ID-only mode (sufficient for
                    # verifying tokens, but cannot mint custom tokens)
                    _firebase_app = firebase_admin.initialize_app(
                        options={"projectId": settings.FIREBASE_PROJECT_ID}
                    )
    return _firebase_app


async def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase JWT token and return decoded claims.

    Returns a dict with at least 'uid' and 'email' keys.
    Raises HTTPException 401 on invalid/expired tokens.
    """
    try:
        _get_firebase_app()
        decoded = firebase_auth.verify_id_token(token, check_revoked=True)
        return decoded
    except firebase_auth.RevokedIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
