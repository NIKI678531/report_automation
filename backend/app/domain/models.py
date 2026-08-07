from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReportStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    FINALIZED = "FINALIZED"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class SnapshotStatus(str, enum.Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"


class ProductCatalog(Base):
    __tablename__ = "product_catalog"
    __table_args__ = (UniqueConstraint("product_code", "valid_from", name="uq_product_catalog_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_code: Mapped[str] = mapped_column(String(32), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    name_en: Mapped[str] = mapped_column(String(255))
    name_zh_hant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    benchmark_code: Mapped[str] = mapped_column(String(32))
    benchmark_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="HKD")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Hong_Kong")
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    template_version: Mapped[str] = mapped_column(String(32), default="3033-v1")
    design_token_version: Mapped[str] = mapped_column(String(32), default="3033-v1")
    expected_constituent_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    formula_profile: Mapped[str] = mapped_column(String(64), default="total-return-v1")
    source: Mapped[str] = mapped_column(String(64), default="APPROVED_IMPORT")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_code: Mapped[str] = mapped_column(String(32), index=True)
    product_name: Mapped[str] = mapped_column(String(255))
    benchmark_code: Mapped[str] = mapped_column(String(32))
    report_date: Mapped[date] = mapped_column(Date)
    language_mode: Mapped[str] = mapped_column(String(20), default="EN")
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus), default=ReportStatus.DRAFT)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    finalized_document_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_version: Mapped[str] = mapped_column(String(32), default="3033-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    documents: Mapped[list[ReportDocument]] = relationship(back_populates="report", cascade="all, delete-orphan")


class DataSnapshot(Base):
    __tablename__ = "data_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    source_policy: Mapped[str] = mapped_column(String(30), default="GOLDEN_FIXTURE")
    mapping_version: Mapped[str] = mapped_column(String(50), default="hstech-v1")
    status: Mapped[SnapshotStatus] = mapped_column(Enum(SnapshotStatus), default=SnapshotStatus.PENDING)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataImport(Base):
    __tablename__ = "data_imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    dataset_type: Mapped[str] = mapped_column(String(50), default="constituents")
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(30), default="upload-v1")
    status: Mapped[str] = mapped_column(String(20), default="VALIDATED")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    diff: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    applied_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportDocument(Base):
    __tablename__ = "report_documents"
    __table_args__ = (UniqueConstraint("report_id", "version", name="uq_report_document_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    template_version: Mapped[str] = mapped_column(String(32), default="3033-v1")
    language_mode: Mapped[str] = mapped_column(String(20), default="EN")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    report: Mapped[Report] = relationship(back_populates="documents")


class RenderJob(Base):
    __tablename__ = "render_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    format: Mapped[str] = mapped_column(String(10))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.QUEUED)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(80), default="queued")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RenderArtifact(Base):
    __tablename__ = "render_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(10))
    storage_key: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(32))
    renderer_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(120), default="local-user")
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NewsItem(Base):
    __tablename__ = "news_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_name: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(String(1000), unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(String(1000))
    summary: Mapped[str] = mapped_column(String(5000))
    security_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    importance: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    match_confidence: Mapped[int] = mapped_column(Integer, default=100)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportNewsSelection(Base):
    __tablename__ = "report_news_selections"
    __table_args__ = (UniqueConstraint("report_id", "news_item_id", name="uq_report_news_item"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title_override: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    summary_override: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
