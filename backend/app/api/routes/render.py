"""Render jobs and artifact delivery.

Rendering is only allowed once a report is finalized, so every artifact traces back to one
finalized document version. Downloads are handed out as HMAC-signed, TTL-bound URLs rather than
raw paths; the signature is bound to the caller, so a copied link is not a second grant.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.storage import storage
from app.domain import service
from app.domain.models import JobStatus, RenderArtifact, RenderJob, ReportStatus
from app.domain.schemas import JobRead, RenderRequest
from app.worker import dispatch_render
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
    if report.status != ReportStatus.FINALIZED:
        raise HTTPException(status_code=422, detail={"error_code": "FINALIZATION_REQUIRED", "message": "Finalize the report before rendering artifacts."})
    # Fail before queuing anything if the report has no document to render.
    service.latest_document(db, report_id)
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
    return FileResponse(storage.resolve(artifact.storage_key), media_type=artifact.mime_type, filename=artifact.storage_key.rsplit("/", 1)[-1])
