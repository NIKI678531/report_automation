"""Synchronous job execution; no broker or separate worker process (ADR-0028)."""
from __future__ import annotations

from app.core.database import SessionLocal
from app.domain.models import JobStatus, RenderJob, Report
from app.domain.service import latest_document
from app.rendering.artifacts import build_artifact


def execute_render(db, job_id: str) -> dict:
    job = db.get(RenderJob, job_id)
    if not job:
        return {"error": "JOB_NOT_FOUND"}
    job.status, job.stage, job.progress = JobStatus.RUNNING, "rendering", 20
    db.commit()
    try:
        report = db.get(Report, job.report_id)
        artifact = build_artifact(db, report, latest_document(db, report.id), job.format)
        job.status, job.stage, job.progress, job.artifact_id = JobStatus.SUCCEEDED, "complete", 100, artifact.id
        job.error = None
    except Exception as error:
        job.status, job.stage = JobStatus.FAILED, "failed"
        job.error = {"error_code": "RENDER_FAILED", "message": str(error), "retryable": True}
        db.commit()
        raise
    db.commit()
    return {"job_id": job.id, "artifact_id": job.artifact_id, "status": job.status.value}


def dispatch_render(job_id: str, db=None) -> None:
    if db is not None:
        execute_render(db, job_id)
    else:
        with SessionLocal() as session:
            execute_render(session, job_id)


def dispatch_translation(job_id: str, db=None) -> None:
    from app.domain.service.translations import execute_translation

    if db is not None:
        for _ in range(3):
            if execute_translation(db, job_id) != "QUEUED":
                break
    else:
        with SessionLocal() as session:
            dispatch_translation(job_id, session)
