from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReportStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    DATA_READY = "DATA_READY"
    EDITING = "EDITING"
    QA_BLOCKED = "QA_BLOCKED"
    READY_TO_FINALIZE = "READY_TO_FINALIZE"
    # Kept so pre-V2.1 rows can be read and revised after migration.
    REVIEW = "REVIEW"
    FINALIZED = "FINALIZED"
    ARCHIVED = "ARCHIVED"


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


class Lane(str, enum.Enum):
    """Whether a snapshot's data is fit to be published.

    ``source_policy`` answers *where the data came from*; the lane answers *may this be
    distributed*. They are orthogonal on purpose: any source that is transcribed, synthetic or
    otherwise not derived from an approved system belongs on TESTING, and every artifact built
    from a TESTING snapshot is watermarked and prefixed so it cannot be mistaken for a deliverable.
    """

    PRODUCTION = "PRODUCTION"
    TESTING = "TESTING"


class ProductCatalog(Base):
    __tablename__ = "product_catalog"
    __table_args__ = (UniqueConstraint("product_code", "valid_from", name="uq_product_catalog_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_code: Mapped[str] = mapped_column(String(32), index=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    name_en: Mapped[str] = mapped_column(String(255))
    name_zh_hant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    constituent_index_code: Mapped[str] = mapped_column(String(32))
    constituent_index_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    benchmark_instrument_code: Mapped[str] = mapped_column(String(32))
    benchmark_instrument_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fund_total_return_instrument_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fund_kpi_product_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trading_calendar_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    constituent_index_code: Mapped[str] = mapped_column(String(32))
    benchmark_instrument_code: Mapped[str] = mapped_column(String(32))
    benchmark_code: Mapped[str] = mapped_column(String(32))
    report_date: Mapped[date] = mapped_column(Date)
    language_mode: Mapped[str] = mapped_column(String(20), default="EN")
    # Denormalised from the active snapshot so the report list can badge the lane without loading
    # every snapshot. Written wherever `active_snapshot_id` is assigned, and never on its own.
    lane: Mapped[str] = mapped_column(String(16), default=Lane.PRODUCTION.value)
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
    # No default: every construction site must state where the data came from. A default here once
    # made GOLDEN_FIXTURE the silent fallback for anything that forgot to say.
    source_policy: Mapped[str] = mapped_column(String(30))
    lane: Mapped[str] = mapped_column(String(16), default=Lane.PRODUCTION.value)
    mapping_version: Mapped[str] = mapped_column(String(50), default="hstech-v1")
    status: Mapped[SnapshotStatus] = mapped_column(Enum(SnapshotStatus), default=SnapshotStatus.PENDING)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SnapshotDataset(Base):
    __tablename__ = "snapshot_datasets"
    __table_args__ = (UniqueConstraint("snapshot_id", "dataset_type", name="uq_snapshot_dataset_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("data_snapshots.id"), index=True)
    dataset_type: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(32))
    source_object: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer)
    coverage: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mapping_version: Mapped[str] = mapped_column(String(64))
    validation_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IndustryMasterRecord(Base):
    __tablename__ = "industry_master"
    __table_args__ = (
        UniqueConstraint("taxonomy", "version", "level", "code", name="uq_industry_master_code"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    taxonomy: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(6))
    parent_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    name_en: Mapped[str] = mapped_column(String(255))
    name_zh_hant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(255))
    source_record_key: Mapped[str] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MappingProfile(Base):
    __tablename__ = "mapping_profiles"
    __table_args__ = (UniqueConstraint("profile_id", "version", name="uq_mapping_profile_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(String(100), index=True)
    dataset_type: Mapped[str] = mapped_column(String(64), index=True)
    source_family: Mapped[str] = mapped_column(String(100))
    selector: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    field_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unit_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    transforms: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    semantic_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
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
    mapping_profile_id: Mapped[str | None] = mapped_column(ForeignKey("mapping_profiles.id"), nullable=True, index=True)
    mapping_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class MetricValue(Base):
    __tablename__ = "metric_values"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "metric_code", "dimension_key", "formula_version",
            name="uq_metric_value_version",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("data_snapshots.id"), index=True)
    metric_code: Mapped[str] = mapped_column(String(100), index=True)
    dimension_key: Mapped[str] = mapped_column(String(255), default="")
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    raw_value: Mapped[str] = mapped_column(String(500))
    unit: Mapped[str] = mapped_column(String(32))
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    formula_version: Mapped[str] = mapped_column(String(64))
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModuleSnapshot(Base):
    __tablename__ = "module_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "module_code", "formula_version", "template_version",
            name="uq_module_snapshot_version",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("data_snapshots.id"), index=True)
    module_code: Mapped[str] = mapped_column(String(64), index=True)
    formula_version: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(64))
    source_dataset_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    metric_value_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    display_format: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    footnote_bindings: Mapped[list[str]] = mapped_column(JSON, default=list)
    checksum: Mapped[str] = mapped_column(String(64))
    input_checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityCheckResult(Base):
    __tablename__ = "quality_check_results"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "result_key", name="uq_snapshot_quality_result"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("data_snapshots.id"), index=True)
    source_dataset_id: Mapped[str | None] = mapped_column(ForeignKey("snapshot_datasets.id"), nullable=True)
    result_key: Mapped[str] = mapped_column(String(255))
    check_id: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actual: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    threshold: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    fix_hint: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    content_manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
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


class ReportNewsCandidate(Base):
    __tablename__ = "report_news_candidates"
    __table_args__ = (UniqueConstraint("report_id", "news_item_id", name="uq_report_news_candidate"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    news_item_id: Mapped[str] = mapped_column(ForeignKey("news_items.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    match_status: Mapped[str] = mapped_column(String(20), default="CONFIRMED")
    match_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NewsFetchRun(Base):
    __tablename__ = "news_fetch_runs"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "snapshot_id", "provider", "scope", "from_date", "to_date",
            name="uq_news_fetch_window",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("data_snapshots.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(20))
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
