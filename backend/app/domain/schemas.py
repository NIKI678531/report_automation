from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import JobStatus, ReportStatus, SnapshotStatus


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_code: str = "3033"
    report_date: date
    language_mode: Literal["EN", "ZH_HANT", "BILINGUAL"] = "EN"


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product_code: str
    ticker: str
    name_en: str
    name_zh_hant: str | None
    benchmark_code: str
    benchmark_name: str | None
    currency: str
    timezone: str
    valid_from: date
    valid_to: date | None
    is_active: bool
    display_order: int
    template_version: str
    design_token_version: str
    expected_constituent_count: int | None
    formula_profile: str
    source: str


class ProductImportRead(BaseModel):
    created: int
    updated: int
    total: int


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product_code: str
    product_name: str
    benchmark_code: str
    report_date: date
    language_mode: str
    status: ReportStatus
    revision: int
    version: int
    active_snapshot_id: str | None
    parent_report_id: str | None
    revision_reason: str | None
    finalized_document_version: int | None
    template_version: str
    created_at: datetime
    updated_at: datetime


class ReportDetail(ReportRead):
    latest_document: dict[str, Any] | None = None
    quality_results: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class SnapshotCreate(BaseModel):
    source_policy: Literal["CDB_ONLY", "GOLDEN_FIXTURE", "UPLOAD_OVERRIDE"] = "GOLDEN_FIXTURE"
    mapping_version: str = "hstech-v1"


class SnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    report_id: str
    as_of_date: date
    source_policy: str
    mapping_version: str
    status: SnapshotStatus
    checksum: str | None
    payload: dict[str, Any]
    quality_results: list[dict[str, Any]]


class ImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    report_id: str
    dataset_type: str
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum: str
    parser_version: str
    status: str
    payload: dict[str, Any]
    validation_results: list[dict[str, Any]]
    diff: dict[str, Any]
    reason: str | None
    applied_snapshot_id: str | None
    # Derived for the UI: counts to summarise the upload at a glance, and a small sample so the
    # user can confirm the file was read the way they expected before applying it.
    summary: dict[str, int] = Field(default_factory=dict)
    preview: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _derive_summary_and_preview(self) -> "ImportRead":
        findings = self.validation_results or []
        rows: list[dict[str, Any]] = []
        for key in ("constituents", "constituent_returns", "sector_mapping", "sector_overrides", "total_return_series"):
            if key in (self.payload or {}):
                rows = self.payload[key]
                break
        self.summary = {
            "rows_parsed": len(rows),
            "blocking": len([item for item in findings if item.get("severity") == "BLOCKING" and item.get("status", "FAILED") != "PASSED"]),
            "warnings": len([item for item in findings if item.get("severity") == "WARNING" and item.get("status", "FAILED") != "PASSED"]),
        }
        sample = rows[:20]
        columns = [key for key in (sample[0].keys() if sample else ()) if not key.startswith("_")]
        self.preview = {"columns": columns, "rows": [{key: row.get(key) for key in columns} for row in sample], "total": len(rows)}
        return self


class ImportApply(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class DocumentUpdate(BaseModel):
    version: int
    content: dict[str, Any]


class FinalizeRequest(BaseModel):
    version: int


class RevisionCreate(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class RenderRequest(BaseModel):
    formats: list[Literal["html", "pdf", "docx"]] = ["html", "pdf", "docx"]


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    report_id: str
    format: str
    status: JobStatus
    progress: int
    stage: str
    error: dict[str, Any] | None
    artifact_id: str | None


class ErrorItem(BaseModel):
    error_code: str
    field: str | None = None
    entity_id: str | None = None
    message: str
    severity: str
    fix_hint: str


class CalculationRead(BaseModel):
    snapshot_id: str
    formula_version: str
    metrics: dict[str, Any]
    quality_results: list[dict[str, Any]]
    document_version: int


class NewsCreate(BaseModel):
    source_name: str
    source_url: str
    published_at: datetime
    title: str
    summary: str
    security_code: str | None = None
    ticker: str | None = None
    importance: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"


class NewsRead(NewsCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    match_confidence: int
    created_at: datetime
    # Provider facts FMP returns alongside the article; persisted in metadata_json rather than
    # as columns so the provider payload stays additive. Lifted here for filtering in the UI.
    site: str | None = None
    provider: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _lift_metadata(cls, value: Any) -> Any:
        metadata = getattr(value, "metadata_json", None)
        if not isinstance(metadata, dict):
            return value
        fields = {"site": metadata.get("site"), "provider": metadata.get("provider")}
        return {**{name: getattr(value, name) for name in cls.model_fields if hasattr(value, name)}, **fields}


class NewsSelectionItem(BaseModel):
    news_item_id: str
    position: int = Field(ge=0)
    title_override: str | None = None
    summary_override: str | None = None


class NewsSelectionUpdate(BaseModel):
    version: int
    items: list[NewsSelectionItem]


class NewsCandidateFetch(BaseModel):
    scope: Literal["CONSTITUENTS", "GENERAL"] = "CONSTITUENTS"
    from_date: date | None = None
    to_date: date | None = None
    page: int = Field(default=0, ge=0, le=100)
    limit: int = Field(default=20, ge=1, le=250)
    #: A key from app.integrations.news.REGISTRY; None uses the environment's configured default.
    provider: str | None = None


class AiDraftRequest(BaseModel):
    version: int
    user_prompt: str = Field(default="", max_length=2000)


class ReviewRead(BaseModel):
    ready: bool
    blocking: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    checks: list[dict[str, Any]]
