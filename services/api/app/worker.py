from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.models import JobStatus, RenderJob, Report
from app.domain.service import latest_document
from app.rendering.artifacts import build_artifact

celery_app = Celery("commentary-worker", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_time_limit=120, task_soft_time_limit=90, worker_prefetch_multiplier=1)


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


@celery_app.task(name="commentary.render", bind=True, autoretry_for=(OSError,), retry_backoff=True, max_retries=2)
def render_job_task(self, job_id: str) -> dict:
    with SessionLocal() as db:
        return execute_render(db, job_id)


def dispatch_render(job_id: str, db=None) -> None:
    if settings.task_mode == "CELERY":
        render_job_task.delay(job_id)
    elif db is not None:
        execute_render(db, job_id)
    else:
        render_job_task.apply(args=[job_id], throw=True)
