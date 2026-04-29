from fastapi import APIRouter, Depends
from google.cloud.firestore_v1.client import Client as FirestoreClient

from app.db import tidb
from app.firestore import get_firestore_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "RetailSG API"}


@router.get("/health/ready")
async def readiness_check(db: FirestoreClient = Depends(get_firestore_db)):
    """Readiness probe — verifies the app can reach Firestore."""
    try:
        # Simple Firestore connectivity check
        db.collection("_health").document("ping").get()
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        return {"status": "not_ready", "database": str(exc)}


@router.get("/health/tidb")
async def tidb_health_check():
    """Probe the TiDB connection. Returns `disabled` when not configured."""
    return await tidb.healthcheck()
