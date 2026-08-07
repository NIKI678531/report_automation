from datetime import date
from typing import Annotated
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domain import service
from app.domain.models import AuditEvent, DataImport, DataSnapshot, JobStatus, NewsItem, ProductCatalog, RenderArtifact, RenderJob, Report, ReportDocument, ReportNewsSelection, ReportStatus
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
    ImportRead,
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
    applied = set((snapshot.payload or {}).get("datasets", {})) if snapshot else set()
    slots = []
    for key, spec in ingestion.REGISTRY.items():
        if spec.legacy:
            continue
        item = imports_by_slot.get(key)
        findings = list(item.validation_results or []) if item else []
        slots.append({
            "key": key,
            "title": spec.title,
            "description": spec.description,
            "required": spec.required,
            "accepts": list(spec.accepts),
            "state": ("APPLIED" if key in applied else item.status) if item else "MISSING",
            "latest_import_id": item.id if item else None,
            "filename": item.original_filename if item else None,
            "rows": _row_count(item.payload) if item else 0,
            "uploaded_at": item.created_at.isoformat() if item else None,
            "blocking": len([finding for finding in findings if finding.get("severity") == "BLOCKING"]),
            "warnings": len([finding for finding in findings if finding.get("severity") == "WARNING"]),
            "applied_snapshot_id": item.applied_snapshot_id if item else None,
        })
    return slots


def _row_count(payload: dict | None) -> int:
    if not payload:
        return 0
    for key in ("constituents", "constituent_returns", "sector_mapping", "sector_overrides", "total_return_series"):
        if key in payload:
            return len(payload[key])
    return 0


@router.post("/reports/{report_id}/imports", response_model=ImportRead, status_code=status.HTTP_201_CREATED)
async def create_import(
    report_id: str,
    db: Db,
    x_request_id: Annotated[str, Depends(request_id)],
    file: UploadFile = File(...),
    dataset_type: str = Form("constituents"),
) -> DataImport:
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
    try:
        payload, collector = ingestion.parse(dataset_type, filename, data, report.report_date)
    except UnicodeError as error:
        raise HTTPException(status_code=422, detail={
            "error_code": "IMPORT_DECODE_FAILED", "message": "The file could not be decoded as UTF-8.",
            "severity": "BLOCKING", "fix_hint": "Re-export the file as UTF-8 (or UTF-8 with BOM) and upload again.",
        }) from error
    # A file with bad rows is a first-class, inspectable resource rather than a 4xx: the user needs
    # to see every finding at once, and REJECTED imports stay queryable in the report's history.
    rejected = collector.has_blocking() or not payload
    validations = collector.as_dicts()
    if not rejected and dataset_type in {"constituents", "final_analytics"}:
        validations = [*quality_checks(payload, service.resolve_product(db, report.product_code, report.report_date).expected_constituent_count), *validations]
    active_payload: dict = {}
    if report.active_snapshot_id:
        active_snapshot = db.get(DataSnapshot, report.active_snapshot_id)
        active_payload = active_snapshot.payload if active_snapshot else {}
    if rejected:
        diff = {"summary": {"added": 0, "removed": 0, "changed": 0}}
    elif spec.legacy:
        diff = diff_dataset(dataset_type, payload, active_payload)
    elif dataset_type == "index_constituents":
        diff = diff_dataset("constituents", payload, active_payload)
    else:
        # Field-level slots do not change the constituent set; the meaningful figure is how many
        # of the securities in the active snapshot this file actually covers.
        rows = payload.get("constituent_returns") or payload.get("sector_mapping") or payload.get("sector_overrides") or []
        active_codes = {row["security_code"] for row in active_payload.get("constituents", [])}
        covered = len([row for row in rows if row["security_code"] in active_codes]) if active_codes else 0
        diff = {"summary": {"added": 0, "removed": 0, "changed": len(rows)}, "rows": len(rows), "covered": covered, "uncovered": max(len(active_codes) - covered, 0)}
    item = DataImport(
        report_id=report.id, dataset_type=dataset_type, original_filename=filename,
        mime_type=file.content_type or "application/octet-stream", size_bytes=len(data), checksum=hashlib.sha256(data).hexdigest(),
        parser_version=f"{dataset_type}-v1", payload=payload, validation_results=validations,
        status="REJECTED" if rejected else "VALIDATED",
        diff=diff,
    )
    db.add(item); db.flush()
    service.audit(db, "import.rejected" if rejected else "import.validated", "import", item.id, x_request_id, {
        "filename": item.original_filename, "dataset_type": dataset_type, **collector.summary(),
    })
    db.commit(); db.refresh(item)
    return item


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


@router.post("/reports/{report_id}/ai/in-review")
def generate_in_review(report_id: str, command: AiDraftRequest, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> dict:
    document = service.ai_assisted_draft(db, service.get_report(db, report_id), command.version, command.user_prompt, x_request_id)
    return {"version": document.version, "checksum": document.checksum, "content": document.content}


@router.post("/news", response_model=NewsRead, status_code=status.HTTP_201_CREATED)
def create_news(command: NewsCreate, db: Db, x_request_id: Annotated[str, Depends(request_id)]) -> NewsItem:
    existing = db.scalar(select(NewsItem).where(NewsItem.source_url == command.source_url))
    if existing:
        return existing
    item = NewsItem(**command.model_dump(), metadata_json={"ingest": "manual", "request_id": x_request_id})
    db.add(item); db.flush(); service.audit(db, "news.created", "news", item.id, x_request_id); db.commit(); db.refresh(item)
    return item


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
    from app.integrations.news import NewsProviderError, fetch_news
    report = service.get_report(db, report_id)
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    month_start = report.report_date.replace(day=1)
    from_date = command.from_date or month_start
    to_date = command.to_date or report.report_date
    if from_date > to_date or to_date > report.report_date:
        raise HTTPException(status_code=422, detail={"error_code": "NEWS_DATE_RANGE_INVALID", "message": "News dates must be ordered and cannot exceed the report date."})
    symbols: list[str] = []
    if command.scope == "CONSTITUENTS":
        if not report.active_snapshot_id:
            raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED", "message": "Constituent news requires an active snapshot."})
        snapshot = db.get(DataSnapshot, report.active_snapshot_id)
        symbols = sorted({str(row.get("ticker", "")).upper() for row in snapshot.payload.get("constituents", []) if row.get("ticker")})
        if not symbols:
            raise HTTPException(status_code=422, detail={"error_code": "CONSTITUENT_TICKERS_REQUIRED"})
    try:
        provider, candidates = await fetch_news(command.provider, command.scope, symbols, from_date, to_date, command.page, command.limit)
    except NewsProviderError as error:
        raise HTTPException(status_code=error.http_status, detail={"error_code": error.code, "message": error.message, "retryable": error.retryable}) from error
    items, created = service.upsert_news_candidates(db, report, candidates, x_request_id, provider=provider)
    return {"provider": provider, "fetched": len(candidates), "created": created, "items": [NewsRead.model_validate(item).model_dump() for item in items]}


@router.get("/reports/{report_id}/news/candidates", response_model=list[NewsRead])
def report_news_candidates(
    report_id: str,
    db: Db,
    query: str | None = None,
    source: str | None = None,
    symbol: str | None = None,
    importance: str | None = None,
) -> list[NewsItem]:
    service.get_report(db, report_id)
    items = list(db.scalars(select(NewsItem).order_by(NewsItem.published_at.desc())))
    items = [item for item in items if report_id in (item.metadata_json or {}).get("report_ids", [])]
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
    if published_at.date() > report.report_date:
        raise HTTPException(status_code=422, detail={"error_code": "NEWS_DATE_RANGE_INVALID", "message": "News cannot be published after the report date."})
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
        db.add(ReportNewsSelection(report_id=report_id, news_item_id=news.id, position=item.position, title_override=item.title_override, summary_override=item.summary_override))
        selected.append({"news_item_id": news.id, "title": item.title_override or news.title, "summary": item.summary_override or news.summary, "source_name": news.source_name, "source_url": news.source_url, "published_at": news.published_at.isoformat()})
    content = dict(current.content); content["sections"] = dict(content["sections"]); content["sections"]["company_news"] = selected
    document = service.update_document(db, report, current.version, content, x_request_id)
    return {"version": document.version, "items": selected}


@router.get("/reports/{report_id}/review", response_model=ReviewRead)
def review(report_id: str, db: Db) -> ReviewRead:
    report = service.get_report(db, report_id); document = service.latest_document(db, report_id)
    checks = []
    if report.active_snapshot_id:
        snapshot = db.get(DataSnapshot, report.active_snapshot_id)
        checks.extend(snapshot.quality_results if snapshot else [])
    else:
        checks.append({"check_id": "SNAPSHOT", "severity": "BLOCKING", "status": "FAILED", "fix_hint": "Create a valid snapshot."})
    sections = document.content.get("sections", {})
    placeholders = any("Add the approved" in str(value) for value in sections.values())
    checks.append({"check_id": "QC-009", "severity": "BLOCKING", "status": "FAILED" if placeholders else "PASSED", "fix_hint": "Replace all editorial placeholders."})
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
@router.put("/reports/{report_id}/document", include_in_schema=False)
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
