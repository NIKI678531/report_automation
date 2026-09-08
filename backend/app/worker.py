"""Synchronous translation dispatch; exports run directly in their download request."""
from app.core.database import SessionLocal


def dispatch_translation(job_id: str, db=None) -> None:
    from app.domain.service.translations import execute_translation

    if db is not None:
        for _ in range(3):
            if execute_translation(db, job_id) != "QUEUED":
                break
    else:
        with SessionLocal() as session:
            dispatch_translation(job_id, session)
