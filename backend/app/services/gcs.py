"""Cloud Storage helper — upload/download AI artifacts.

All AI-generated files (images, PDFs, embeddings) go through here.
Bucket: gs://{AI_GCS_BUCKET}/
Path convention: {store_id}/{artifact_type}/{artifact_id}.{ext}

All GCS SDK calls are synchronous, so we wrap them in asyncio.to_thread()
to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _bucket_name() -> str:
    return settings.AI_GCS_BUCKET


def _sync_upload(bucket: str, destination_path: str, data: bytes, content_type: str) -> str:
    """Blocking upload — runs inside asyncio.to_thread()."""
    from google.cloud import storage

    client = storage.Client(project=settings.GCP_PROJECT_ID)
    blob = client.bucket(bucket).blob(destination_path)
    blob.upload_from_string(data, content_type=content_type)
    return f"gs://{bucket}/{destination_path}"


def _sync_download(bucket_name: str, blob_path: str) -> bytes:
    """Blocking download — runs inside asyncio.to_thread()."""
    from google.cloud import storage

    client = storage.Client(project=settings.GCP_PROJECT_ID)
    blob = client.bucket(bucket_name).blob(blob_path)
    return blob.download_as_bytes()


async def upload_bytes(
    data: bytes,
    destination_path: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload bytes to GCS (non-blocking). Returns the gs:// URI."""
    bucket = _bucket_name()
    try:
        uri = await asyncio.to_thread(
            _sync_upload, bucket, destination_path, data, content_type,
        )
        logger.info("Uploaded %d bytes to %s", len(data), uri)
        return uri
    except Exception as exc:
        logger.error("GCS upload failed: %s", exc)
        raise


async def download_bytes(gcs_uri: str) -> bytes:
    """Download bytes from a gs:// URI (non-blocking)."""
    try:
        if not gcs_uri.startswith("gs://"):
            raise ValueError(f"Invalid GCS URI: {gcs_uri}")
        parts = gcs_uri[5:].split("/", 1)
        bucket_name = parts[0]
        blob_path = parts[1] if len(parts) > 1 else ""

        return await asyncio.to_thread(_sync_download, bucket_name, blob_path)
    except Exception as exc:
        logger.error("GCS download failed for %s: %s", gcs_uri, exc)
        raise


def artifact_path(
    store_id: str,
    artifact_type: str,
    artifact_id: str,
    ext: str = "json",
) -> str:
    """Generate a conventional GCS path for an artifact."""
    return f"{store_id}/{artifact_type}/{artifact_id}.{ext}"
