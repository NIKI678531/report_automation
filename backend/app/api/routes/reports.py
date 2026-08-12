"""The report itself: lifecycle, the editable document, the review gate and the preview.

Everything numeric arrives through the snapshot and calculation endpoints in
:mod:`.datasets`; nothing here computes a report fact.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import service
from app.domain.models import DataSnapshot, RenderArtifact, Report
from app.domain.schemas import (
    AiDraftRequest,
    DocumentUpdate,
    FinalizeRequest,
    ReportCreate,
    ReportDetail,
    ReportRead,
    ReviewRead,
    RevisionCreate,
)
from app.rendering.html import render_html
from .deps import Db, RequestId

router = APIRouter()


@router.get("/reports", response_model=list[ReportRead])
def list_reports(db: Db) -> list[Report]:
    return list(db.scalars(select(Report).order_by(Report.created_at.desc())))


@router.post("/reports", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_report(command: ReportCreate, db: Db, x_request_id: RequestId) -> Report:
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
    checks.append({"check_id": "LANGUAGE", "severity": "WARNING", "status": "PASSED" if report.language_mode == "EN" else "WARNING", "fix_hint": "Complete every configured language block."})
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


@router.get("/reports/{report_id}/preview", include_in_schema=False)
@router.post("/reports/{report_id}/preview")
def preview(report_id: str, db: Db) -> Response:
    report = service.get_report(db, report_id)
    document = service.latest_document(db, report_id)
    return Response(render_html(report, document.content), media_type="text/html")
