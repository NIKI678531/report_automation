"""The report itself: lifecycle, the editable document, the review gate and the preview.

Everything numeric arrives through the snapshot and calculation endpoints in
:mod:`.datasets`; nothing here computes a report fact.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Header, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import service
from app.core.config import settings
from app.domain.service import translations
from app.domain.schemas import TranslationJobRead
from app.worker import dispatch_translation
from app.domain.models import DataSnapshot, Report, ReportStatus
from app.domain.schemas import (
    AiDraftRequest,
    DocumentUpdate,
    FinalizeRequest,
    LanguageVariantCreate,
    LanguageVariantSync,
    PreviewRequest,
    ReportCreate,
    ReportDetail,
    ReportRead,
    ReviewRead,
    RevisionCreate,
)
from app.rendering.html import render_html
from app.rendering.disclaimer import DisclaimerResourceError
from .deps import Db, RequestId

router = APIRouter()


@router.get("/reports", response_model=list[ReportRead])
def list_reports(db: Db, include_archived: bool = False) -> list[Report]:
    query = select(Report)
    if not include_archived:
        query = query.where(Report.status != ReportStatus.ARCHIVED)
    # Filtered in SQL rather than after the fetch, so a caller with a narrow product scope never
    # has out-of-scope rows loaded into the process in the first place.
    visible = service.visible_product_codes()
    if visible is not None:
        query = query.where(Report.product_code.in_(visible))
    return list(db.scalars(query.order_by(Report.created_at.desc())))


@router.post("/reports", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_report(command: ReportCreate, db: Db, x_request_id: RequestId) -> Report:
    return service.create_report(db, command, x_request_id)


@router.post(
    "/reports/{source_report_id}/language-variants",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_language_variant(
    source_report_id: str,
    command: LanguageVariantCreate,
    db: Db,
    x_request_id: RequestId,
) -> Report:
    return service.create_language_variant(
        db, service.get_report(db, source_report_id), command, x_request_id
    )


@router.post(
    "/reports/{source_report_id}/language-variants/{target_report_id}/sync",
    response_model=ReportRead,
)
def sync_language_variant(
    source_report_id: str,
    target_report_id: str,
    command: LanguageVariantSync,
    db: Db,
    x_request_id: RequestId,
) -> Report:
    return service.sync_language_variant(
        db,
        service.get_report(db, source_report_id),
        service.get_report(db, target_report_id),
        command,
        x_request_id,
    )


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: str, version: int, db: Db, x_request_id: RequestId) -> Response:
    service.delete_report(db, service.get_report(db, report_id), version, x_request_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reports/{source_report_id}/language-variants/{target_report_id}/translations", response_model=TranslationJobRead, status_code=202)
def translate_report(source_report_id: str, target_report_id: str, command: LanguageVariantSync, db: Db, x_request_id: RequestId, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    job, created = translations.create_translation(db, source_report_id, target_report_id, command, idempotency_key, x_request_id)
    if created:
        try:
            dispatch_translation(job.id, db)
        except Exception:
            translations.fail_translation(db, job.id, "TRANSLATION_DISPATCH_FAILED")
        db.refresh(job)
    return job


@router.get("/reports/{report_id}/translation-jobs/latest", response_model=TranslationJobRead | None)
def latest_translation(report_id: str, db: Db):
    return translations.latest_translation(db, report_id)


@router.get("/reports/{report_id}/translation-jobs/{job_id}", response_model=TranslationJobRead)
def translation_status(report_id: str, job_id: str, db: Db):
    return translations.translation_status(db, report_id, job_id)


def detail(db: Session, report: Report) -> ReportDetail:
    document = service.latest_document(db, report.id)
    source = db.get(Report, report.translation_source_report_id) if report.translation_source_report_id else None
    quality = []
    if report.active_snapshot_id:
        snapshot = db.get(DataSnapshot, report.active_snapshot_id)
        quality = snapshot.quality_results if snapshot else []
    base = ReportRead.model_validate(report).model_dump()
    return ReportDetail(
        **base,
        translation_enabled=settings.translation_provider == "OPENAI_COMPATIBLE" and not settings.translation_problems(),
        translation_source_language_mode=source.language_mode if source else None,
        latest_document={
            "version": document.version,
            "checksum": document.checksum,
            "content": service.document_content_for_read(report, document),
        },
        quality_results=quality,
    )


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: str, db: Db) -> ReportDetail:
    return detail(db, service.get_report(db, report_id))


@router.post("/reports/{report_id}/revisions", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_revision(report_id: str, command: RevisionCreate, db: Db, x_request_id: RequestId) -> Report:
    return service.create_revision(db, service.get_report(db, report_id), command.reason, x_request_id)


@router.post("/reports/{report_id}/ai/in-review")
def generate_in_review(report_id: str, command: AiDraftRequest, db: Db, x_request_id: RequestId) -> dict:
    document = service.ai_assisted_draft(db, service.get_report(db, report_id), command.version, command.user_prompt, x_request_id)
    return {"version": document.version, "checksum": document.checksum, "content": document.content}


@router.get("/reports/{report_id}/review", response_model=ReviewRead)
def review(report_id: str, db: Db) -> ReviewRead:
    report = service.get_report(db, report_id); document = service.latest_document(db, report_id)
    checks = service.release_gate_checks(db, report, document)
    blocking = [item for item in checks if item["severity"] == "BLOCKING" and item["status"] != "PASSED"]
    warnings = [item for item in checks if item["severity"] == "WARNING" and item["status"] != "PASSED"]
    return ReviewRead(ready=not blocking, blocking=blocking, warnings=warnings, checks=checks)


@router.patch("/reports/{report_id}/document")
def update_document(report_id: str, command: DocumentUpdate, db: Db, x_request_id: RequestId) -> dict:
    report = service.get_report(db, report_id)
    document = service.update_document(db, report, command.version, command.content, x_request_id)
    return {"version": document.version, "checksum": document.checksum, "content": document.content}


@router.post("/reports/{report_id}/finalize", response_model=ReportRead)
def finalize(report_id: str, command: FinalizeRequest, db: Db, x_request_id: RequestId) -> Report:
    report = service.get_report(db, report_id)
    return service.finalize(db, report, command.version, x_request_id)


def _preview_response(report: Report, content: dict) -> Response:
    try:
        html = render_html(report, content, preview=True, layout_mode="paged")
    except DisclaimerResourceError as error:
        raise HTTPException(status_code=503, detail={
            "error_code": "DISCLAIMER_RESOURCE_INVALID",
            "message": "The approved disclaimer resource is unavailable or invalid.",
            "severity": "BLOCKING",
            "fix_hint": "Restore the approved versioned disclaimer resource before previewing.",
        }) from error
    return Response(html, media_type="text/html")


@router.get("/reports/{report_id}/preview", include_in_schema=False)
def preview_saved(report_id: str, db: Db) -> Response:
    report = service.get_report(db, report_id)
    return _preview_response(
        report,
        service.preview_document_content(db, report),
    )


@router.post("/reports/{report_id}/preview")
def preview_draft(
    report_id: str,
    db: Db,
    command: PreviewRequest | None = None,
) -> Response:
    report = service.get_report(db, report_id)
    return _preview_response(
        report,
        service.preview_document_content(
            db,
            report,
            expected_version=command.version if command else None,
            content=command.content if command else None,
        ),
    )
