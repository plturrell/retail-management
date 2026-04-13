"""Persistent storage for AI invocation results and pipeline outputs.

Two tables:
  - ai_invocations: audit log of every Gemini call (prompt hash, model, tokens, cost)
  - ai_artifacts: normalized outputs (pricing drafts, summaries, catalog enrichments)
    with optional GCS URI for large blobs (images, PDFs, embeddings).
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models._mixins import uuid_pk, created_at_col


class AIInvocation(Base):
    """Audit row for every Gemini call that flows through ai_gateway."""
    __tablename__ = "ai_invocations"

    id: Mapped[uuid_pk]
    request_id: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(default=False, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[created_at_col]

    artifacts = relationship("AIArtifact", back_populates="invocation", lazy="raise")

    def __repr__(self) -> str:
        return f"<AIInvocation {self.request_id} purpose={self.purpose}>"


class AIArtifact(Base):
    """Normalized AI output — pricing draft, analytics summary, catalog enrichment, etc."""
    __tablename__ = "ai_artifacts"

    id: Mapped[uuid_pk]
    invocation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_invocations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    store_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    artifact_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )  # "pricing_draft", "analytics_summary", "catalog_enrichment", "ocr_result"
    status: Mapped[str] = mapped_column(
        String(24), default="completed", nullable=False,
    )  # "pending", "processing", "completed", "failed"
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    gcs_uri: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
    )  # gs://bucket/path for large blobs
    created_at: Mapped[created_at_col]
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    invocation = relationship("AIInvocation", back_populates="artifacts", lazy="raise")

    def __repr__(self) -> str:
        return f"<AIArtifact {self.artifact_type} status={self.status}>"
