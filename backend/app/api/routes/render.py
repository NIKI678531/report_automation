"""Render jobs and artifact delivery.

Rendering is only allowed once a report is finalized, so every artifact traces back to one
finalized document version. Downloads are handed out as HMAC-signed, TTL-bound URLs rather than
raw paths; the signature is bound to the caller, so a copied link is not a second grant.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.storage import storage
from app.domain import service
from app.domain.models import JobStatus, RenderArtifact, RenderJob, ReportStatus
from app.domain.schemas import JobRead, RenderRequest
from app.worker import dispatch_render
from app.rendering.artifacts import renderer_version_for
from .deps import Db, RequestId

router = APIRouter()


@router.post("/reports/{report_id}/renders", response_model=list[JobRead], status_code=status.HTTP_202_ACCEPTED)
def render_outputs(
    report_id: str,
    command: RenderRequest,
    db: Db,
    x_request_id: RequestId,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> list[RenderJob]:
    report = service.get_report(db, report_id)
    service.ensure_report_not_archived(report)
    if report.status != ReportStatus.FINALIZED:
        raise HTTPException(status_code=422, detail={"error_code": "FINALIZATION_REQUIRED", "message": "Finalize the report before rendering artifacts."})
    # Fail before queuing anything if the report has no document to render.
    document = service.latest_document(db, report_id)
    jobs = []
    for format_name in dict.fromkeys(command.formats):
        key = f"{idempotency_key}:{format_name}" if idempotency_key else None
        if key:
            existing = db.scalar(select(RenderJob).where(RenderJob.idempotency_key == key))
            if existing:
                jobs.append(existing)
                continue
        current_artifact = db.scalar(select(RenderArtifact).where(
            RenderArtifact.report_id == report.id,
            RenderArtifact.document_version == document.version,
            RenderArtifact.format == format_name,
            RenderArtifact.renderer_version == renderer_version_for(format_name),
        ).order_by(RenderArtifact.created_at.desc()))
        if current_artifact and current_artifact.content_manifest.get("language_mode", report.language_mode) == report.language_mode:
            job = RenderJob(
                report_id=report.id,
                format=format_name,
                status=JobStatus.SUCCEEDED,
                progress=100,
                stage="reused",
                idempotency_key=key,
                artifact_id=current_artifact.id,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            jobs.append(job)
            continue
        job = RenderJob(report_id=report.id, format=format_name, status=JobStatus.QUEUED, progress=0, stage="queued", idempotency_key=key)
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            # Two concurrent requests with the same Idempotency-Key: the SELECT above found
            # nothing for both, and the unique index arbitrated. The loser adopts the winner's job,
            # which is what "repeated idempotency keys return the original job" has to mean under
            # concurrency rather than only in sequence.
            db.rollback()
            existing = db.scalar(select(RenderJob).where(RenderJob.idempotency_key == key)) if key else None
            if existing is None:
                raise
            jobs.append(existing)
            continue
        db.refresh(job)
        try:
            dispatch_render(job.id, db)
            db.refresh(job)
        except Exception as error:
            job.status, job.stage = JobStatus.FAILED, "failed"
            job.error = {"error_code": "RENDER_FAILED", "message": str(error), "retryable": True}
        # A CELERY dispatch returns with the job still QUEUED: the worker has it and has not
        # finished. Recording that as "render.failed" put a false failure in the regulated audit
        # trail on every asynchronous render.
        service.audit(db, _dispatch_action(job.status), "render_job", job.id, x_request_id, {"format": format_name})
        db.commit(); db.refresh(job)
        jobs.append(job)
    return jobs


def _dispatch_action(status_value: JobStatus) -> str:
    if status_value == JobStatus.SUCCEEDED:
        return "render.completed"
    return "render.queued" if status_value == JobStatus.QUEUED else "render.failed"


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Db) -> RenderJob:
    job = db.get(RenderJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error_code": "JOB_NOT_FOUND"})
    return job


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, request: Request, db: Db):
    artifact = db.get(RenderArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail={"error_code": "ARTIFACT_NOT_FOUND"})
    principal = request.state.principal
    expires_at = int(time.time()) + settings.download_ttl_seconds
    signature = storage.sign(artifact.id, principal.subject, expires_at)
    return {"download_url": f"{settings.api_prefix}/artifacts/{artifact.id}/content?expires={expires_at}&signature={signature}", "expires_at": expires_at}


@router.get("/artifacts/{artifact_id}/content", include_in_schema=False)
def artifact_content(artifact_id: str, request: Request, expires: int, signature: str, db: Db):
    artifact = db.get(RenderArtifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail={"error_code": "ARTIFACT_NOT_FOUND"})
    if not storage.verify(artifact.id, request.state.principal.subject, expires, signature):
        raise HTTPException(status_code=403, detail={"error_code": "DOWNLOAD_SIGNATURE_INVALID"})
    try:
        # Streamed from the object-storage port rather than read from a path: the deployment has no
        # persistent volume, so the bytes are not necessarily on this container's disk.
        body = storage.open(artifact.storage_key)
    except FileNotFoundError:
        # The row outlived the object. That is what a restart looks like when artifacts were kept
        # on container-local disk, and reporting it as a 500 would blame the request instead.
        raise HTTPException(status_code=404, detail={
            "error_code": "ARTIFACT_CONTENT_MISSING",
            "message": "The artifact is recorded but its stored object is gone.",
            "fix_hint": "Re-render the report. If it keeps happening, the deployment is storing artifacts on container-local disk.",
        })
    filename = artifact.storage_key.rsplit("/", 1)[-1]
    return StreamingResponse(
        body.chunks,
        media_type=artifact.mime_type,
        headers={
            "Content-Length": str(body.size_bytes),
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
