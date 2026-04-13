"""Unit tests for the async job dispatcher.

Uses the in-memory SQLite test DB from conftest to test:
- Job dispatch creates artifact with pending status
- Local execution transitions pending → processing → completed
- Failed jobs transition to failed status
- Invalid job type raises ValueError
"""
from __future__ import annotations

import asyncio
import uuid as uuid_mod
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TestSessionLocal
from app.models.ai_artifact import AIArtifact
from app.models.store import Store
from app.models.user import User, UserStoreRole, RoleEnum
from app.services.job_dispatcher import JOB_TYPES, dispatch_job, _run_local, _execute_job


@pytest_asyncio.fixture
async def test_store():
    """Create a store for testing."""
    from datetime import time
    async with TestSessionLocal() as session:
        store = Store(
            name="Test AI Store",
            location="Test",
            address="Test Address",
            business_hours_start=time(10, 0),
            business_hours_end=time(22, 0),
        )
        session.add(store)
        user = User(
            firebase_uid="test-firebase-uid",
            email="test@example.com",
            full_name="Test User",
        )
        session.add(user)
        await session.flush()
        role = UserStoreRole(
            user_id=user.id,
            store_id=store.id,
            role=RoleEnum.owner,
        )
        session.add(role)
        await session.commit()
        await session.refresh(store)
        return store


# ── Job type validation ──────────────────────────────────────────

class TestJobTypes:

    def test_known_job_types(self):
        assert "catalog_enrichment" in JOB_TYPES
        assert "ocr_receipt" in JOB_TYPES
        assert "ocr_invoice" in JOB_TYPES
        assert "ocr_sales_ledger" in JOB_TYPES
        assert "embedding_generation" in JOB_TYPES
        assert "bulk_pricing_review" in JOB_TYPES

    @pytest.mark.asyncio
    async def test_invalid_job_type_raises(self, test_store):
        with pytest.raises(ValueError, match="Unknown job type"):
            await dispatch_job(
                job_type="nonexistent_job",
                store_id=test_store.id,
                payload={},
            )


# ── Dispatch creates artifact ────────────────────────────────────

class TestDispatch:

    @pytest.mark.asyncio
    async def test_dispatch_creates_pending_artifact(self, test_store):
        with patch("app.database.async_session_factory", TestSessionLocal):
            artifact_id = await dispatch_job(
                job_type="catalog_enrichment",
                store_id=test_store.id,
                payload={"sku_data": {"sku_code": "TEST-001"}},
            )

        assert artifact_id  # non-empty string

        async with TestSessionLocal() as session:
            result = await session.execute(
                select(AIArtifact).where(AIArtifact.id == UUID(artifact_id))
            )
            artifact = result.scalar_one_or_none()
            assert artifact is not None
            assert artifact.artifact_type == "catalog_enrichment"
            assert artifact.status in ("pending", "processing", "completed")
            assert artifact.store_id == test_store.id

    @pytest.mark.asyncio
    async def test_dispatch_stores_input_payload(self, test_store):
        with patch("app.database.async_session_factory", TestSessionLocal):
            artifact_id = await dispatch_job(
                job_type="ocr_receipt",
                store_id=test_store.id,
                payload={"file_name": "receipt.jpg"},
                gcs_input_uri="gs://bucket/receipt.jpg",
            )

        async with TestSessionLocal() as session:
            result = await session.execute(
                select(AIArtifact).where(AIArtifact.id == UUID(artifact_id))
            )
            artifact = result.scalar_one()
            assert artifact.payload["input"]["file_name"] == "receipt.jpg"
            assert artifact.payload["gcs_input_uri"] == "gs://bucket/receipt.jpg"


# ── Local execution state transitions ────────────────────────────

class TestLocalExecution:

    @pytest.mark.asyncio
    async def test_successful_job_transitions_to_completed(self, test_store):
        # Create artifact manually
        async with TestSessionLocal() as session:
            artifact = AIArtifact(
                store_id=test_store.id,
                artifact_type="ocr_receipt",
                status="pending",
                payload={"input": {}, "gcs_input_uri": None},
            )
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)
            artifact_id = str(artifact.id)

        with patch("app.database.async_session_factory", TestSessionLocal):
            with patch(
                "app.services.job_dispatcher._execute_job",
                new_callable=AsyncMock,
                return_value={"status": "done", "text": "OCR complete"},
            ):
                await _run_local("ocr_receipt", artifact_id)

        async with TestSessionLocal() as session:
            result = await session.execute(
                select(AIArtifact).where(AIArtifact.id == UUID(artifact_id))
            )
            artifact = result.scalar_one()
            assert artifact.status == "completed"
            assert artifact.payload["output"]["status"] == "done"

    @pytest.mark.asyncio
    async def test_failed_job_transitions_to_failed(self, test_store):
        async with TestSessionLocal() as session:
            artifact = AIArtifact(
                store_id=test_store.id,
                artifact_type="embedding_generation",
                status="pending",
                payload={"input": {}},
            )
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)
            artifact_id = str(artifact.id)

        with patch("app.database.async_session_factory", TestSessionLocal):
            with patch(
                "app.services.job_dispatcher._execute_job",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Embedding API crashed"),
            ):
                await _run_local("embedding_generation", artifact_id)

        async with TestSessionLocal() as session:
            result = await session.execute(
                select(AIArtifact).where(AIArtifact.id == UUID(artifact_id))
            )
            artifact = result.scalar_one()
            assert artifact.status == "failed"
            assert "Embedding API crashed" in artifact.payload["error"]

    @pytest.mark.asyncio
    async def test_missing_artifact_logs_error(self):
        with patch("app.database.async_session_factory", TestSessionLocal):
            # Should not raise, just log
            await _run_local("ocr_receipt", str(uuid_mod.uuid4()))


# ── Execute job routing ──────────────────────────────────────────

class TestExecuteJobRouting:

    @pytest.mark.asyncio
    async def test_catalog_enrichment_calls_gateway(self):
        mock_resp = AsyncMock()
        mock_resp.return_value = type("R", (), {"text": '{"description": "test"}', "request_id": "abc"})()

        with patch("app.services.ai_gateway.invoke", mock_resp):
            result = await _execute_job("catalog_enrichment", {"input": {"sku_data": {}}})
            assert "enriched_text" in result

    @pytest.mark.asyncio
    async def test_ocr_uses_document_pipeline(self):
        with patch(
            "app.services.document_ocr.process_document_from_gcs",
            new_callable=AsyncMock,
            return_value={"status": "completed", "page_count": 1},
        ) as mock_process:
            result = await _execute_job(
                "ocr_receipt",
                {"input": {"file_name": "receipt.jpg"}, "gcs_input_uri": "gs://bucket/receipt.jpg"},
            )

        assert result["status"] == "completed"
        mock_process.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sales_ledger_ocr_uses_document_pipeline(self):
        with patch(
            "app.services.document_ocr.process_document_from_gcs",
            new_callable=AsyncMock,
            return_value={"status": "completed", "structured": {"result": {"pages": []}}},
        ) as mock_process:
            result = await _execute_job(
                "ocr_sales_ledger",
                {
                    "input": {"file_name": "ledger.pdf", "document_kind": "sales_ledger"},
                    "gcs_input_uri": "gs://bucket/ledger.pdf",
                },
            )

        assert result["status"] == "completed"
        assert "structured" in result
        mock_process.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_embeddings_returns_stub(self):
        result = await _execute_job("embedding_generation", {})
        assert result["status"] == "embeddings_not_yet_implemented"

    @pytest.mark.asyncio
    async def test_unknown_type_returns_no_handler(self):
        result = await _execute_job("unknown_type", {})
        assert result["status"] == "no_handler"
