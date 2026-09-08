from __future__ import annotations

from datetime import timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import Principal, bind_principal, current_principal, reset_principal
from app.integrations.translation import ensure_translation_available, translate_texts
from ..document import checksum
from ..editorial_translation import PROMPT_VERSION, TranslationError, translate_review
from ..models import Report, TranslationJob, utcnow
from ..schemas import LanguageVariantSync
from .audit import audit
from .documents import latest_document, update_document
from .lifecycle import ensure_report_editable, ensure_report_not_archived
from .reports import ai_number_check, get_report


def _failure(code: str, *, retryable=False) -> dict:
    return {"error_code": code, "message": "Translation was not applied. The saved report is unchanged.", "fix_hint": "Check translation settings or reload the report and retry.", "retryable": retryable}


def _request_hash(source_id: str, target_id: str, command: LanguageVariantSync) -> str:
    return checksum({"source": source_id, "target": target_id, **command.model_dump(), "model": settings.translation_model, "provider": settings.translation_provider, "endpoint": settings.translation_base_url, "prompt": PROMPT_VERSION})


def _pair(db: Session, source_id: str, target_id: str, source_version: int, target_version: int, *, locked=False):
    source, target = get_report(db, source_id), get_report(db, target_id)
    ensure_report_not_archived(source)
    ensure_report_editable(target)
    if (source.product_code, source.report_date, source.revision, source.lane) != (target.product_code, target.report_date, target.revision, target.lane):
        raise HTTPException(422, detail=_failure("LANGUAGE_VARIANT_CONTEXT_MISMATCH"))
    if source.language_mode == target.language_mode or "EN" not in {source.language_mode, target.language_mode} or not {source.language_mode, target.language_mode} <= {"EN", "ZH_HANS", "ZH_HANT"}:
        raise HTTPException(422, detail=_failure("TRANSLATION_LANGUAGE_PAIR_INVALID"))
    source_document, target_document = latest_document(db, source_id, for_update=locked), latest_document(db, target_id, for_update=locked)
    if (source_document.version, target_document.version) != (source_version, target_version):
        raise HTTPException(409, detail=_failure("VERSION_CONFLICT"))
    return source, target, source_document, target_document


def create_translation(db: Session, source_id: str, target_id: str, command: LanguageVariantSync, key: str, request_id: str) -> tuple[TranslationJob, bool]:
    get_report(db, source_id)
    get_report(db, target_id)
    caller = current_principal()
    if caller is None or not caller.has_at_least("EDITOR"):
        raise HTTPException(403, detail=_failure("ROLE_FORBIDDEN"))
    request_hash = _request_hash(source_id, target_id, command)
    identity = checksum([caller.subject, source_id, target_id, key])
    existing = db.scalar(select(TranslationJob).where(TranslationJob.idempotency_hash == identity))
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, detail=_failure("IDEMPOTENCY_CONFLICT"))
        return existing, False
    _pair(db, source_id, target_id, command.source_document_version, command.target_document_version)
    try:
        ensure_translation_available()
    except TranslationError as error:
        raise HTTPException(503, detail=_failure(error.code)) from None
    job = TranslationJob(
        source_report_id=source_id, target_report_id=target_id,
        source_document_version=command.source_document_version, target_document_version=command.target_document_version,
        actor=caller.subject, request_id=request_id, idempotency_hash=identity, request_hash=request_hash,
        model=settings.translation_model, expires_at=utcnow() + timedelta(seconds=240),
    )
    db.add(job)
    try:
        db.flush()
        audit(db, "translation.queued", "translation_job", job.id, request_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(TranslationJob).where(TranslationJob.idempotency_hash == identity))
        if not existing or existing.request_hash != request_hash:
            raise HTTPException(409, detail=_failure("IDEMPOTENCY_CONFLICT")) from None
        return existing, False
    return job, True


def translation_status(db: Session, target_id: str, job_id: str) -> TranslationJob:
    get_report(db, target_id)
    job = db.get(TranslationJob, job_id)
    if not job or job.target_report_id != target_id:
        raise HTTPException(404, detail={"error_code": "JOB_NOT_FOUND"})
    get_report(db, job.source_report_id)
    if job.status in {"QUEUED", "RUNNING"} and job.expires_at.replace(tzinfo=timezone.utc) < utcnow():
        db.execute(update(TranslationJob).where(TranslationJob.id == job_id, TranslationJob.status.in_(["QUEUED", "RUNNING"])).values(status="FAILED", error=_failure("TRANSLATION_EXPIRED", retryable=True)))
        db.commit()
        db.refresh(job)
    return job


def latest_translation(db: Session, target_id: str) -> TranslationJob | None:
    get_report(db, target_id)
    job = db.scalar(select(TranslationJob).where(TranslationJob.target_report_id == target_id).order_by(TranslationJob.created_at.desc(), TranslationJob.id.desc()))
    return translation_status(db, target_id, job.id) if job else None


def fail_translation(db: Session, job_id: str, code: str) -> None:
    db.rollback()
    db.execute(update(TranslationJob).where(TranslationJob.id == job_id, TranslationJob.status.in_(["QUEUED", "RUNNING"])).values(status="FAILED", error=_failure(code, retryable=True)))
    db.commit()


def execute_translation(db: Session, job_id: str) -> str:
    # Let the database evaluate expiry. After a retry, an already-loaded job can contain a
    # timezone-naive MySQL/SQLite timestamp; ORM "evaluate" would compare it with utcnow()
    # in Python and raise before claiming the next attempt. expire_all below reloads state.
    claimed = db.execute(update(TranslationJob).where(TranslationJob.id == job_id, TranslationJob.status == "QUEUED", TranslationJob.expires_at > utcnow()).values(status="RUNNING", attempts=TranslationJob.attempts + 1).execution_options(synchronize_session=False))
    db.commit()
    if not claimed.rowcount:
        return "IGNORED"
    db.expire_all()
    job = db.get(TranslationJob, job_id)
    principal_token = None
    try:
        command = LanguageVariantSync(source_document_version=job.source_document_version, target_document_version=job.target_document_version)
        if job.request_hash != _request_hash(job.source_report_id, job.target_report_id, command):
            raise TranslationError("TRANSLATION_CONFIGURATION_CHANGED")
        source, target, source_document, target_document = _pair(db, job.source_report_id, job.target_report_id, job.source_document_version, job.target_document_version)
        principal_token = bind_principal(Principal(subject=job.actor, role="EDITOR", product_scope=frozenset({target.product_code})))
        source_content, target_content = source_document.content, target_document.content
        source_language, target_language = source.language_mode, target.language_mode
        source_id, target_id, source_version = source.id, target.id, source_document.version
        model = job.model
        db.rollback()
        content, preserved = translate_review(source_content, target_content, source_id=source_id, target_id=target_id, source_version=source_version, source_language=source_language, target_language=target_language, model=model, translate=translate_texts)
        db.expire_all()
        job = db.scalar(select(TranslationJob).where(TranslationJob.id == job_id).with_for_update())
        if job.status != "RUNNING" or job.expires_at.replace(tzinfo=timezone.utc) < utcnow():
            raise TranslationError("TRANSLATION_EXPIRED")
        list(db.scalars(select(Report).where(Report.id.in_([job.source_report_id, job.target_report_id])).order_by(Report.id).with_for_update().execution_options(populate_existing=True)))
        source, target, source_document, target_document = _pair(db, job.source_report_id, job.target_report_id, job.source_document_version, job.target_document_version, locked=True)
        if ai_number_check(db, target, SimpleNamespace(content=content))["status"] != "PASSED":
            raise TranslationError("TRANSLATION_UNBOUND_NUMBER")
        changed = checksum(content) != target_document.checksum
        job.status = "SUCCEEDED"
        job.error = None
        job.preserved_fields = preserved
        job.result_document_version = target_document.version + int(changed)
        audit(db, "translation.completed", "translation_job", job.id, job.request_id, {"document_version": job.result_document_version, "preserved_fields": preserved}, actor=job.actor)
        if changed:
            update_document(db, target, target_document.version, content, job.request_id)
        else:
            db.commit()
        return "SUCCEEDED"
    except Exception as error:
        db.rollback()
        job = db.get(TranslationJob, job_id)
        code = error.code if isinstance(error, TranslationError) else error.detail.get("error_code", "TRANSLATION_FAILED") if isinstance(error, HTTPException) and isinstance(error.detail, dict) else "TRANSLATION_FAILED"
        retry = isinstance(error, TranslationError) and error.retryable and job.attempts < 3
        if job.status == "RUNNING":
            job.status = "QUEUED" if retry else "FAILED"
            job.error = _failure(code, retryable=isinstance(error, TranslationError) and error.retryable)
            audit(db, "translation.retry" if retry else "translation.failed", "translation_job", job.id, job.request_id, {"error_code": code}, actor=job.actor)
            db.commit()
        return job.status
    finally:
        if principal_token is not None:
            reset_principal(principal_token)
