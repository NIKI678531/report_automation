from datetime import date, timezone
from typing import Annotated
from urllib.parse import urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domain import service
from app.domain.models import AuditEvent, DataImport, DataSnapshot, IndustryMasterRecord, JobStatus, MappingProfile, MetricValue, ModuleSnapshot, NewsFetchRun, NewsItem, ProductCatalog, QualityCheckResult, RenderArtifact, RenderJob, Report, ReportDocument, ReportNewsSelection, ReportStatus, utcnow
from app.domain.schemas import (
    DocumentUpdate,
    FinalizeRequest,
    ReportCreate,
    ReportDetail,
    ReportRead,
    RevisionCreate,
    RenderRequest,
    JobRead,
    ImportApply,
    ImportCreateRead,
    ImportRead,
    MappingProfileCreate,
    MappingProfileRead,
    AiDraftRequest,
    CalculationRead,
    NewsCreate,
    NewsCandidateFetch,
    NewsRead,
    NewsSelectionUpdate,
    ProductImportRead,
    ProductRead,
    ReviewRead,
    SnapshotCreate,
    SnapshotRead,
)

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]


def request_id(value: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> str:
    return value or str(uuid4())


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "commentary-api", "architecture": {"frontend": "React", "backend": "FastAPI"}}


@router.get("/products", response_model=list[ProductRead])
def list_products(db: Db, as_of_date: date | None = None, include_inactive: bool = False) -> list[ProductCatalog]:
    return service.list_products(db, as_of_date or date.today(), include_inactive)


@router.post("/products/import", response_model=ProductImportRead)
async def import_products(
    request: Request,
    db: Db,
    x_request_id: Annotated[str, Depends(request_id)],
    file: UploadFile = File(...),
) -> dict[str, int]:
    from app.domain.products import parse_product_catalog_csv
    if request.state.principal.role != "ADMIN":
        raise HTTPException(status_code=403, detail={"error_code": "PRODUCT_ADMIN_REQUIRED"})
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail={"error_code": "PRODUCT_CATALOG_FORMAT", "message": "Product catalog must be a CSV file."})
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"error_code": "FILE_TOO_LARGE"})
    try:
        rows = parse_product_catalog_csv(data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error_code": "PRODUCT_CATALOG_INVALID", "message": str(error), "severity": "BLOCKING"}) from error
    return service.import_products(db, rows, x_request_id)


@router.post("/industry-master/import", status_code=status.HTTP_201_CREATED)
async def import_industry_master(
    request: Request,
    db: Db,
    x_request_id: Annotated[str, Depends(request_id)],
    file: UploadFile = File(...),
) -> dict:
    from app.domain.industry import parse_industry_master_csv
    if request.state.principal.role != "ADMIN":
        raise HTTPException(status_code=403, detail={"error_code": "INDUSTRY_ADMIN_REQUIRED"})
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail={"error_code": "INDUSTRY_MASTER_FORMAT", "message": "Industry master must be a CSV file."})
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"error_code": "FILE_TOO_LARGE"})
    try:
        rows = parse_industry_master_csv(data)
    except (UnicodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail={
            "error_code": "INDUSTRY_MASTER_INVALID",
            "message": str(error),
            "severity": "BLOCKING",
            "fix_hint": "Use the standard HSICS industry-master columns and correct all reported hierarchy errors.",
        }) from error
    return service.import_industry_master(db, rows, x_request_id)


@router.get("/industry-master")
def list_industry_master(db: Db, as_of_date: date | None = None) -> list[dict]:
    query = select(IndustryMasterRecord)
    if as_of_date:
        from sqlalchemy import or_
        query = query.where(
            IndustryMasterRecord.valid_from <= as_of_date,
            or_(IndustryMasterRecord.valid_to.is_(None), IndustryMasterRecord.valid_to >= as_of_date),
        )
    rows = db.scalars(query.order_by(IndustryMasterRecord.version, IndustryMasterRecord.level, IndustryMasterRecord.code))
    return [{
        "taxonomy": item.taxonomy,
        "version": item.version,
        "level": item.level,
        "code": item.code,
        "parent_code": item.parent_code,
        "name_en": item.name_en,
        "name_zh_hant": item.name_zh_hant,
        "valid_from": item.valid_from,
        "valid_to": item.valid_to,
        "source": item.source,
        "checksum": item.checksum,
    } for item in rows]


@router.get("/mapping-profiles", response_model=list[MappingProfileRead])
def list_mapping_profiles(db: Db, dataset_type: str | None = None, include_drafts: bool = False) -> list[MappingProfile]:
    query = select(MappingProfile)
    if dataset_type:
        query = query.where(MappingProfile.dataset_type == dataset_type)
    if not include_drafts:
        query = query.where(MappingProfile.status == "APPROVED")
    return list(db.scalars(query.order_by(MappingProfile.dataset_type, MappingProfile.profile_id, MappingProfile.version.desc())))


@router.post("/mapping-profiles", response_model=MappingProfileRead, status_code=status.HTTP_201_CREATED)
def create_mapping_profile(
    request: Request,
    command: MappingProfileCreate,
    db: Db,
    x_request_id: Annotated[str, Depends(request_id)],
) -> MappingProfile:
    from app.domain import ingestion
    if request.state.principal.role != "ADMIN":
        raise HTTPException(status_code=403, detail={"error_code": "MAPPING_ADMIN_REQUIRED"})
    if ingestion.get_spec(command.dataset_type) is None:
        raise HTTPException(status_code=422, detail={
            "error_code": "UNSUPPORTED_DATASET",
            "message": f"Unknown dataset type '{command.dataset_type}'.",
        })
    required_fields = command.selector.get("required_fields")
    extensions = command.selector.get("extensions")
    if not isinstance(required_fields, list) or not required_fields:
        raise HTTPException(status_code=422, detail={
            "error_code": "MAPPING_SELECTOR_INVALID",
            "message": "selector.required_fields must be a non-empty list.",
        })
    if not isinstance(extensions, list) or not extensions:
        raise HTTPException(status_code=422, detail={
            "error_code": "MAPPING_SELECTOR_INVALID",
            "message": "selector.extensions must be a non-empty list.",
        })
    missing_fields = sorted(set(required_fields) - set(command.field_map))
    if missing_fields:
        raise HTTPException(status_code=422, detail={
            "error_code": "MAPPING_FIELDS_MISSING",
            "message": f"field_map is missing selector fields: {', '.join(missing_fields)}.",
        })
    existing = db.scalar(select(MappingProfile).where(
        MappingProfile.profile_id == command.profile_id,
        MappingProfile.version == command.version,
    ))
    if existing:
        raise HTTPException(status_code=409, detail={
            "error_code": "MAPPING_PROFILE_IMMUTABLE",
            "message": "That mapping profile version already exists.",
            "fix_hint": "Create a new version instead of overwriting an approved mapping.",
        })
    profile = MappingProfile(
        **command.model_dump(),
        approved_by=request.state.principal.subject if command.status == "APPROVED" else None,
    )
    db.add(profile)
    db.flush()
    service.audit(db, "mapping_profile.created", "mapping_profile", profile.id, x_request_id, {
        "profile_id": profile.profile_id,
        "version": profile.version,
        "status": profile.status,
    })
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/reports", response_model=list[ReportRead])
def list_reports(db: Db) -> list[Report]:
    return list(db.scalars(select(Report).order_by(Report.created_at.desc())))


@router.post("/reports", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_report(command: ReportCreate, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> Report:
    return service.create_report(db, command, x_request_id)


def detail(db: Session, report: Report) -> ReportDetail:
    document = service.latest_document(db, report.id)
    quality = []
    if report.active_snapshot_id:
        snapshot = db.get(DataSnapshot, report.active_snapshot_id)
        quality = snapshot.quality_results if snapshot else []
    artifacts = list(db.scalars(select(RenderArtifact).where(RenderArtifact.report_id == report.id).order_by(RenderArtifact.created_at.desc())))
    base = ReportRead.model_validate(report).model_dump()
    return ReportDetail(
        **base,
        latest_document={"version": document.version, "checksum": document.checksum, "content": document.content},
        quality_results=quality,
        artifacts=[{
            "id": item.id,
            "format": item.format,
            "mime_type": item.mime_type,
            "size_bytes": item.size_bytes,
            "checksum": item.checksum,
            "content_manifest_checksum": item.content_manifest.get("checksum"),
        } for item in artifacts],
    )


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: str, db: Db) -> ReportDetail:
    return detail(db, service.get_report(db, report_id))


@router.post("/reports/{report_id}/revisions", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_revision(report_id: str, command: RevisionCreate, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> Report:
    return service.create_revision(db, service.get_report(db, report_id), command.reason, x_request_id)


@router.post("/reports/{report_id}/snapshots", response_model=SnapshotRead, status_code=status.HTTP_201_CREATED)
def create_snapshot(report_id: str, command: SnapshotCreate, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> DataSnapshot:
    report = service.get_report(db, report_id)
    return service.create_snapshot(db, report, command.source_policy, command.mapping_version, x_request_id)


@router.get("/reports/{report_id}/snapshots", response_model=list[SnapshotRead])
def list_snapshots(report_id: str, db: Db) -> list[DataSnapshot]:
    service.get_report(db, report_id)
    return list(db.scalars(select(DataSnapshot).where(DataSnapshot.report_id == report_id).order_by(DataSnapshot.created_at.desc())))


@router.get("/reports/{report_id}/snapshots/{snapshot_id}", response_model=SnapshotRead)
def get_snapshot(report_id: str, snapshot_id: str, db: Db) -> DataSnapshot:
    snapshot = db.get(DataSnapshot, snapshot_id)
    if not snapshot or snapshot.report_id != report_id:
        raise HTTPException(status_code=404, detail={"error_code": "SNAPSHOT_NOT_FOUND"})
    return snapshot


@router.get("/reports/{report_id}/datasets")
def list_datasets(report_id: str, db: Db) -> list[dict]:
    """Per-slot ingestion state, so the UI can show what is loaded and what is still missing."""
    from app.domain import ingestion
    report = service.get_report(db, report_id)
    imports_by_slot: dict[str, DataImport] = {}
    for item in db.scalars(select(DataImport).where(DataImport.report_id == report_id).order_by(DataImport.created_at.asc())):
        imports_by_slot[item.dataset_type] = item
    snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    slots = []
    for key, spec in ingestion.REGISTRY.items():
        item = imports_by_slot.get(key)
        findings = list(item.validation_results or []) if item else []
        is_applied = bool(snapshot and service.dataset_present(snapshot.payload or {}, key))
        slots.append({
            "key": key,
            "title": spec.title,
            "description": spec.description,
            "required": spec.required,
            "accepts": list(spec.accepts),
            "state": "APPLIED" if is_applied else item.status if item else "MISSING",
            "latest_import_id": item.id if item else None,
            "filename": item.original_filename if item else None,
            "rows": _row_count(item.payload) if item else 0,
            "uploaded_at": item.created_at.isoformat() if item else None,
            "blocking": len([finding for finding in findings if finding.get("severity") == "BLOCKING"]),
            "warnings": len([finding for finding in findings if finding.get("severity") == "WARNING"]),
            "applied_snapshot_id": item.applied_snapshot_id if item else None,
        })
    from app.domain.industry import effective_hsics_records
    industry_rows = effective_hsics_records(db, report.report_date)
    industry_versions = {row.version for row in industry_rows}
    industry_applied = bool(snapshot and service.dataset_present(snapshot.payload or {}, "industry_master"))
    slots.append({
        "key": "industry_master",
        "title": "HSICS industry master",
        "description": "Centrally managed report-date-effective HSICS taxonomy used for every industry aggregation.",
        "required": True,
        "accepts": [".csv"],
        "state": "APPLIED" if industry_applied else "AVAILABLE" if len(industry_versions) == 1 else "MISSING",
        "latest_import_id": None,
        "filename": None,
        "rows": len(industry_rows),
        "uploaded_at": None,
        "blocking": 0 if len(industry_versions) == 1 else 1,
        "warnings": 0,
        "applied_snapshot_id": snapshot.id if industry_applied else None,
    })
    return slots


def _row_count(payload: dict | None) -> int:
    if not payload:
        return 0
    for key in ("constituents", "constituent_returns", "total_return_series", "fund_kpis", "trading_calendar", "index_events"):
        if key in payload:
            return len(payload[key])
    return 0


@router.post("/reports/{report_id}/imports", response_model=ImportCreateRead, status_code=status.HTTP_201_CREATED)
async def create_import(
    report_id: str,
    db: Db,
    x_request_id: Annotated[str, Depends(request_id)],
    file: UploadFile = File(...),
    dataset_type: str = Form("constituents"),
) -> ImportCreateRead:
    import hashlib
    from app.domain import ingestion
    from app.domain.calculation import quality_checks
    from app.domain.imports import diff_dataset
    report = service.get_report(db, report_id)
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    spec = ingestion.get_spec(dataset_type)
    if spec is None:
        raise HTTPException(status_code=422, detail={
            "error_code": "UNSUPPORTED_DATASET",
            "message": f"Unknown dataset type '{dataset_type}'.",
            "fix_hint": f"Supported datasets: {', '.join(sorted(ingestion.REGISTRY))}.",
        })
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"error_code": "FILE_TOO_LARGE", "message": "Uploads are limited to 20 MB."})
    filename = file.filename or "upload"
    profile = None
    profile_matches: list[tuple[MappingProfile, object]] = []
    approved_profiles = list(db.scalars(select(MappingProfile).where(MappingProfile.status == "APPROVED")))
    profile_matches = ingestion.matching_profiles(approved_profiles, filename, data)
    matching_dataset = [item for item in profile_matches if item[0].dataset_type == dataset_type]
    if len(matching_dataset) == 1:
        profile = matching_dataset[0][0]
    try:
        payload, collector = ingestion.parse(dataset_type, filename, data, report.report_date, profile)
    except UnicodeError as error:
        raise HTTPException(status_code=422, detail={
            "error_code": "IMPORT_DECODE_FAILED", "message": "The file could not be decoded as UTF-8.",
            "severity": "BLOCKING", "fix_hint": "Re-export the file as UTF-8 (or UTF-8 with BOM) and upload again.",
        }) from error
    # A file with bad rows is a first-class, inspectable resource rather than a 4xx: the user needs
    # to see every finding at once, and REJECTED imports stay queryable in the report's history.
    if profile is None and profile_matches:
        candidate_types = sorted({item[0].dataset_type for item in profile_matches})
        collector = ingestion.FindingCollector()
        collector.add(
            "MAP-001",
            f"'{filename}' does not uniquely match the requested {dataset_type} profile.",
            fix_hint=f"This file matches: {', '.join(candidate_types)}. Select the corresponding dataset or approve a new profile.",
            entity_id=candidate_types[0],
        )
        payload = {}
    rejected = collector.has_blocking() or not payload
    validations = collector.as_dicts()
    if not rejected and dataset_type in {"constituents", "final_analytics"}:
        validations = [*quality_checks(payload, service.resolve_product(db, report.product_code, report.report_date).expected_constituent_count), *validations]
    active_payload: dict = {}
    if report.active_snapshot_id:
        active_snapshot = db.get(DataSnapshot, report.active_snapshot_id)
        active_payload = active_snapshot.payload if active_snapshot else {}
    replacing_dataset = service.dataset_present(active_payload, dataset_type)
    if rejected:
        diff = {"summary": {"added": 0, "removed": 0, "changed": 0}}
    elif dataset_type == "index_constituents":
        diff = diff_dataset("constituents", payload, active_payload)
    else:
        row_keys = ("constituent_returns", "total_return_series", "fund_kpis", "trading_calendar", "index_events")
        rows = next((payload[key] for key in row_keys if payload.get(key)), [])
        diff = {"summary": {"added": 0, "removed": 0, "changed": len(rows)}, "rows": len(rows)}
        if dataset_type == "constituent_returns":
            active_codes = {row["security_code"] for row in active_payload.get("constituents", [])}
            covered = len([row for row in rows if row["security_code"] in active_codes]) if active_codes else 0
            diff.update({"covered": covered, "uncovered": max(len(active_codes) - covered, 0)})
    item = DataImport(
        report_id=report.id, dataset_type=dataset_type, original_filename=filename,
        mime_type=file.content_type or "application/octet-stream", size_bytes=len(data), checksum=hashlib.sha256(data).hexdigest(),
        parser_version=f"{dataset_type}-mapping-v2", mapping_profile_id=profile.id if profile else None,
        mapping_version=profile.version if profile else None, payload=payload, validation_results=validations,
        status=("NEEDS_MAPPING" if rejected and any(item.get("error_code", "").startswith("MAP-") for item in validations) else "REJECTED") if rejected else "VALIDATED",
        diff=diff,
    )
    db.add(item); db.flush()
    service.audit(db, "import.rejected" if rejected else "import.validated", "import", item.id, x_request_id, {
        "filename": item.original_filename, "dataset_type": dataset_type, **collector.summary(),
    })
    db.commit(); db.refresh(item)
    return ImportCreateRead(
        **ImportRead.model_validate(item).model_dump(),
        apply_mode="OVERWRITE" if replacing_dataset else "FIRST_APPLY",
        requires_reason=replacing_dataset,
    )


@router.get("/reports/{report_id}/imports", response_model=list[ImportRead])
def list_imports(report_id: str, db: Db) -> list[DataImport]:
    service.get_report(db, report_id)
    return list(db.scalars(select(DataImport).where(DataImport.report_id == report_id).order_by(DataImport.created_at.desc())))


@router.get("/reports/{report_id}/data-diff")
def data_diff(report_id: str, db: Db) -> dict:
    service.get_report(db, report_id)
    item = db.scalar(select(DataImport).where(DataImport.report_id == report_id).order_by(DataImport.created_at.desc()))
    return item.diff if item else {"added": [], "removed": [], "changed": [], "summary": {"added": 0, "removed": 0, "changed": 0}}


@router.post("/reports/{report_id}/imports/{import_id}/apply", response_model=SnapshotRead)
def apply_import(report_id: str, import_id: str, command: ImportApply, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> DataSnapshot:
    report = service.get_report(db, report_id)
    item = db.get(DataImport, import_id)
    if not item:
        raise HTTPException(status_code=404, detail={"error_code": "IMPORT_NOT_FOUND"})
    return service.apply_import(db, report, item, command.reason, x_request_id)


@router.post("/reports/{report_id}/calculations", response_model=CalculationRead)
def calculations(report_id: str, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> CalculationRead:
    report = service.get_report(db, report_id)
    metrics, document, results = service.run_calculation(db, report, x_request_id)
    return CalculationRead(snapshot_id=report.active_snapshot_id or "", formula_version=str(document.content["formula_version"]), metrics=metrics, quality_results=results, document_version=document.version)


@router.get("/reports/{report_id}/metrics")
def report_metrics(report_id: str, db: Db) -> list[dict]:
    report = service.get_report(db, report_id)
    if not report.active_snapshot_id:
        return []
    rows = db.scalars(select(MetricValue).where(MetricValue.snapshot_id == report.active_snapshot_id).order_by(MetricValue.metric_code))
    return [{
        "id": item.id,
        "metric_code": item.metric_code,
        "dimension_key": item.dimension_key,
        "value": str(item.value) if item.value is not None else None,
        "raw_value": item.raw_value,
        "unit": item.unit,
        "period_start": item.period_start,
        "period_end": item.period_end,
        "formula_version": item.formula_version,
        "lineage": item.lineage,
    } for item in rows]


@router.get("/reports/{report_id}/modules")
def report_modules(report_id: str, db: Db) -> list[dict]:
    report = service.get_report(db, report_id)
    if not report.active_snapshot_id:
        return []
    rows = db.scalars(select(ModuleSnapshot).where(ModuleSnapshot.snapshot_id == report.active_snapshot_id).order_by(ModuleSnapshot.module_code))
    return [{
        "id": item.id,
        "module_code": item.module_code,
        "formula_version": item.formula_version,
        "template_version": item.template_version,
        "source_dataset_ids": item.source_dataset_ids,
        "metric_value_ids": item.metric_value_ids,
        "checksum": item.checksum,
        "input_checksum": item.input_checksum,
    } for item in rows]


@router.get("/reports/{report_id}/quality-results")
def report_quality_results(report_id: str, db: Db) -> list[dict]:
    report = service.get_report(db, report_id)
    if not report.active_snapshot_id:
        return []
    rows = db.scalars(select(QualityCheckResult).where(QualityCheckResult.snapshot_id == report.active_snapshot_id).order_by(QualityCheckResult.check_id, QualityCheckResult.result_key))
    return [{
        "id": item.id,
        "check_id": item.check_id,
        "severity": item.severity,
        "status": item.status,
        "entity_id": item.entity_id,
        "actual": item.actual,
        "threshold": item.threshold,
        "fix_hint": item.fix_hint,
    } for item in rows]


@router.post("/reports/{report_id}/ai/in-review")
def generate_in_review(report_id: str, command: AiDraftRequest, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> dict:
    document = service.ai_assisted_draft(db, service.get_report(db, report_id), command.version, command.user_prompt, x_request_id)
    return {"version": document.version, "checksum": document.checksum, "content": document.content}


@router.get("/news", response_model=list[NewsRead])
def list_news(db: Db, security_code: str | None = None, importance: str | None = None) -> list[NewsItem]:
    query = select(NewsItem).order_by(NewsItem.published_at.desc())
    if security_code:
        query = query.where(NewsItem.security_code == security_code)
    if importance:
        query = query.where(NewsItem.importance == importance.upper())
    return list(db.scalars(query))


@router.get("/news/providers")
def list_news_providers() -> list[dict]:
    """Which news providers this environment can actually reach, so the UI can disable the rest."""
    from app.integrations import news

    return news.list_providers()


@router.post("/reports/{report_id}/news/candidates/fetch")
async def fetch_news_candidates(report_id: str, command: NewsCandidateFetch, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> dict:
    from app.integrations.news import NewsProviderError, fetch_news, get_spec
    report = service.get_report(db, report_id)
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    month_start = report.report_date.replace(day=1)
    from_date = command.from_date or month_start
    to_date = command.to_date or report.report_date
    if from_date > to_date or to_date > report.report_date:
        raise HTTPException(status_code=422, detail={"error_code": "NEWS_DATE_RANGE_INVALID", "message": "News dates must be ordered and cannot exceed the report date."})
    symbols: list[str] = []
    constituents: list[dict] = []
    try:
        provider_key = get_spec(command.provider).key
    except NewsProviderError as error:
        raise HTTPException(status_code=error.http_status, detail={"error_code": error.code, "message": error.message, "retryable": error.retryable}) from error
    context_snapshot = service.resolve_news_constituent_snapshot(db, report)
    if not context_snapshot and command.ensure:
        return {
            "provider": provider_key,
            "fetched": 0,
            "created": 0,
            "ensured": False,
            "skip_reason": "CONSTITUENT_SNAPSHOT_UNAVAILABLE" if command.scope == "CONSTITUENTS" else "SNAPSHOT_UNAVAILABLE",
            "items": [],
        }
    if command.scope == "CONSTITUENTS":
        if not context_snapshot:
            raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED", "message": "Constituent news requires an active snapshot."})
        if context_snapshot.status.value != "VALID":
            if command.ensure:
                return {
                    "provider": provider_key,
                    "fetched": 0,
                    "created": 0,
                    "ensured": False,
                    "skip_reason": "SNAPSHOT_NOT_VALID",
                    "items": [],
                }
            raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_NOT_VALID", "message": "Constituent news requires a valid active snapshot."})
        constituents = list(context_snapshot.payload.get("constituents", []))
        symbols = sorted({str(row.get("ticker", "")).upper() for row in constituents if row.get("ticker")})
        if not symbols:
            raise HTTPException(status_code=422, detail={"error_code": "CONSTITUENT_TICKERS_REQUIRED"})
    fetch_run = None
    try:
        if command.ensure:
            existing_items = service.list_news_candidates_for_report_context(db, report)
            successful_run = db.scalar(select(NewsFetchRun).where(
                NewsFetchRun.snapshot_id == context_snapshot.id,
                NewsFetchRun.provider == provider_key,
                NewsFetchRun.scope == command.scope,
                NewsFetchRun.from_date == from_date,
                NewsFetchRun.to_date == to_date,
                NewsFetchRun.status == "SUCCEEDED",
            ).order_by(NewsFetchRun.completed_at.desc()))
            if successful_run:
                return {
                    "provider": provider_key,
                    "fetched": 0,
                    "created": 0,
                    "ensured": False,
                    "skip_reason": "CANDIDATES_ALREADY_EXIST" if existing_items else "WINDOW_ALREADY_ENSURED",
                    "items": [NewsRead.model_validate(item).model_dump() for item in existing_items],
                }
            fetch_run = db.scalar(select(NewsFetchRun).where(
                NewsFetchRun.report_id == report.id,
                NewsFetchRun.snapshot_id == context_snapshot.id,
                NewsFetchRun.provider == provider_key,
                NewsFetchRun.scope == command.scope,
                NewsFetchRun.from_date == from_date,
                NewsFetchRun.to_date == to_date,
            ))
            if fetch_run is None:
                fetch_run = NewsFetchRun(
                    report_id=report.id,
                    snapshot_id=context_snapshot.id,
                    provider=provider_key,
                    scope=command.scope,
                    from_date=from_date,
                    to_date=to_date,
                    status="RUNNING",
                )
                db.add(fetch_run)
            else:
                fetch_run.status = "RUNNING"
                fetch_run.error_code = None
            db.commit()
        provider, candidates = await fetch_news(
            command.provider,
            command.scope,
            symbols,
            from_date,
            to_date,
            command.page,
            command.limit,
            constituents=constituents,
        )
    except NewsProviderError as error:
        if fetch_run:
            fetch_run.status = "FAILED"
            fetch_run.error_code = error.code
            fetch_run.completed_at = utcnow()
            db.commit()
        raise HTTPException(status_code=error.http_status, detail={"error_code": error.code, "message": error.message, "retryable": error.retryable}) from error
    items, created = service.upsert_news_candidates(db, report, candidates, x_request_id, provider=provider)
    if fetch_run:
        fetch_run.status = "SUCCEEDED"
        fetch_run.fetched_count = len(candidates)
        fetch_run.matched_count = len(items)
        fetch_run.completed_at = utcnow()
        db.commit()
    return {"provider": provider, "fetched": len(candidates), "created": created, "ensured": bool(command.ensure), "items": [NewsRead.model_validate(item).model_dump() for item in items]}


@router.get("/reports/{report_id}/news/candidates", response_model=list[NewsRead])
def report_news_candidates(
    report_id: str,
    db: Db,
    query: str | None = None,
    source: str | None = None,
    symbol: str | None = None,
    importance: str | None = None,
) -> list[NewsItem]:
    report = service.get_report(db, report_id)
    items = service.list_news_candidates_for_report_context(db, report)
    if query:
        needle = query.casefold()
        items = [item for item in items if needle in f"{item.title} {item.summary} {item.ticker or ''}".casefold()]
    if source:
        items = [item for item in items if item.source_name.casefold() == source.casefold()]
    if symbol:
        items = [item for item in items if (item.ticker or "").casefold() == symbol.casefold()]
    if importance:
        items = [item for item in items if item.importance == importance.upper()]
    return items


@router.post("/reports/{report_id}/news/candidates", response_model=NewsRead, status_code=status.HTTP_201_CREATED)
def add_report_news_candidate(report_id: str, command: NewsCreate, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> NewsItem:
    """Manually add a candidate the provider missed, scoped to this report like a fetched one."""
    report = service.get_report(db, report_id)
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    published_at = command.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    published_date = published_at.astimezone(ZoneInfo("Asia/Hong_Kong")).date()
    if not report.report_date.replace(day=1) <= published_date <= report.report_date:
        raise HTTPException(status_code=422, detail={"error_code": "NEWS_DATE_RANGE_INVALID", "message": "News must be published inside the report month."})
    candidate = {
        "source_name": command.source_name, "source_url": command.source_url, "published_at": published_at,
        "title": command.title, "summary": command.summary, "ticker": command.ticker,
        "metadata_json": {"provider": "MANUAL", "scope": "MANUAL", "site": urlparse(command.source_url).hostname},
    }
    items, _ = service.upsert_news_candidates(db, report, [candidate], x_request_id, provider="MANUAL")
    return items[0]


@router.put("/reports/{report_id}/news")
def select_news(report_id: str, command: NewsSelectionUpdate, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> dict:
    report = service.get_report(db, report_id)
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    current = service.latest_document(db, report_id)
    if current.version != command.version:
        raise HTTPException(status_code=409, detail={"error_code": "VERSION_CONFLICT", "current_version": current.version})
    db.query(ReportNewsSelection).filter(ReportNewsSelection.report_id == report_id).delete()
    selected = []
    for item in sorted(command.items, key=lambda value: value.position):
        news = db.get(NewsItem, item.news_item_id)
        if not news:
            raise HTTPException(status_code=422, detail={"error_code": "NEWS_NOT_FOUND", "news_item_id": item.news_item_id})
        news_published_at = news.published_at
        if news_published_at.tzinfo is None:
            news_published_at = news_published_at.replace(tzinfo=timezone.utc)
        published_hkt = news_published_at.astimezone(ZoneInfo("Asia/Hong_Kong"))
        if not report.report_date.replace(day=1) <= published_hkt.date() <= report.report_date:
            raise HTTPException(status_code=422, detail={"error_code": "NEWS_DATE_RANGE_INVALID", "message": "Selected news must be published inside the report month.", "news_item_id": news.id})
        db.add(ReportNewsSelection(report_id=report_id, news_item_id=news.id, position=item.position, title_override=item.title_override, summary_override=item.summary_override))
        selected.append({"news_item_id": news.id, "title": item.title_override or news.title, "summary": item.summary_override or news.summary, "source_name": news.source_name, "source_url": news.source_url, "published_at": news.published_at.isoformat(), "published_at_hkt": published_hkt.strftime("%Y-%m-%d %H:%M HKT"), "ticker": news.ticker})
    content = dict(current.content); content["sections"] = dict(content["sections"]); content["sections"]["company_news"] = selected
    document = service.update_document(db, report, current.version, content, x_request_id)
    return {"version": document.version, "items": selected}


@router.get("/reports/{report_id}/review", response_model=ReviewRead)
def review(report_id: str, db: Db) -> ReviewRead:
    report = service.get_report(db, report_id); document = service.latest_document(db, report_id)
    checks = service.release_gate_checks(db, report, document)
    checks.append({"check_id": "LANGUAGE", "severity": "WARNING", "status": "PASSED" if report.language_mode == "EN" else "WARNING", "fix_hint": "Complete every configured language block."})
    blocking = [item for item in checks if item["severity"] == "BLOCKING" and item["status"] != "PASSED"]
    warnings = [item for item in checks if item["severity"] == "WARNING" and item["status"] != "PASSED"]
    return ReviewRead(ready=not blocking, blocking=blocking, warnings=warnings, checks=checks)


@router.get("/audit")
def list_audit(db: Db, report_id: str | None = None, limit: int = 100) -> list[dict]:
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(max(limit, 1), 500))
    events = list(db.scalars(query))
    if report_id:
        events = [event for event in events if event.entity_id == report_id or event.details.get("report_id") == report_id]
    return [{"id": event.id, "actor": event.actor, "action": event.action, "entity_type": event.entity_type, "entity_id": event.entity_id, "request_id": event.request_id, "details": event.details, "created_at": event.created_at} for event in events]


@router.patch("/reports/{report_id}/document")
def update_document(report_id: str, command: DocumentUpdate, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> dict:
    report = service.get_report(db, report_id)
    document = service.update_document(db, report, command.version, command.content, x_request_id)
    return {"version": document.version, "checksum": document.checksum, "content": document.content}


@router.post("/reports/{report_id}/finalize", response_model=ReportRead)
def finalize(report_id: str, command: FinalizeRequest, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> Report:
    report = service.get_report(db, report_id)
    return service.finalize(db, report, command.version, x_request_id)


@router.get("/reports/{report_id}/preview", include_in_schema=False)
@router.post("/reports/{report_id}/preview")
def preview(report_id: str, db: Db) -> Response:
    from app.rendering.html import render_html
    report = service.get_report(db, report_id)
    document = service.latest_document(db, report_id)
    return Response(render_html(report, document.content), media_type="text/html")


@router.post("/reports/{report_id}/renders", response_model=list[JobRead], status_code=status.HTTP_202_ACCEPTED)
def render_outputs(
    report_id: str,
    command: RenderRequest,
    db: Db,
    x_request_id: Annotated[str, Depends(request_id)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> list[RenderJob]:
    from app.worker import dispatch_render
    report = service.get_report(db, report_id)
    if report.status != ReportStatus.FINALIZED:
        raise HTTPException(status_code=422, detail={"error_code": "FINALIZATION_REQUIRED", "message": "Finalize the report before rendering artifacts."})
    document = service.latest_document(db, report_id)
    jobs = []
    for format_name in dict.fromkeys(command.formats):
        key = f"{idempotency_key}:{format_name}" if idempotency_key else None
        if key:
            existing = db.scalar(select(RenderJob).where(RenderJob.idempotency_key == key))
            if existing:
                jobs.append(existing)
                continue
        job = RenderJob(report_id=report.id, format=format_name, status=JobStatus.QUEUED, progress=0, stage="queued", idempotency_key=key)
        db.add(job); db.commit(); db.refresh(job)
        try:
            dispatch_render(job.id, db)
            db.refresh(job)
        except Exception as error:
            job.status, job.stage = JobStatus.FAILED, "failed"
            job.error = {"error_code": "RENDER_FAILED", "message": str(error), "retryable": True}
        service.audit(db, "render.completed" if job.status == JobStatus.SUCCEEDED else "render.failed", "render_job", job.id, x_request_id, {"format": format_name})
        db.commit(); db.refresh(job)
        jobs.append(job)
    return jobs


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Db) -> RenderJob:
    job = db.get(RenderJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error_code": "JOB_NOT_FOUND"})
    return job


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, request: Request, db: Db):
    import time
    from app.core.config import settings
    from app.core.storage import storage
    artifact = db.get(RenderArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail={"error_code": "ARTIFACT_NOT_FOUND"})
    principal = request.state.principal
    expires_at = int(time.time()) + settings.download_ttl_seconds
    signature = storage.sign(artifact.id, principal.subject, expires_at)
    return {"download_url": f"{settings.api_prefix}/artifacts/{artifact.id}/content?expires={expires_at}&signature={signature}", "expires_at": expires_at}


@router.get("/artifacts/{artifact_id}/content", include_in_schema=False)
def artifact_content(artifact_id: str, request: Request, expires: int, signature: str, db: Db):
    from app.core.storage import storage
    artifact = db.get(RenderArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail={"error_code": "ARTIFACT_NOT_FOUND"})
    if not storage.verify(artifact.id, request.state.principal.subject, expires, signature):
        raise HTTPException(status_code=403, detail={"error_code": "DOWNLOAD_SIGNATURE_INVALID"})
    return FileResponse(storage.resolve(artifact.storage_key), media_type=artifact.mime_type, filename=artifact.storage_key.rsplit("/", 1)[-1])
