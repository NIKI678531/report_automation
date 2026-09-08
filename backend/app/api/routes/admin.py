"""Operational endpoints: the liveness probe and the audit trail.

Neither belongs to a single report, which is why they sit outside the report-scoped modules.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.domain.models import AuditEvent
from .deps import Db, require_role

router = APIRouter()

MAX_AUDIT_PAGE = 500


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "commentary-api", "architecture": {"frontend": "React", "backend": "FastAPI"}}


@router.get("/health/deep", dependencies=[require_role("ADMIN", error_code="HEALTH_ACCESS_FORBIDDEN")])
def dependency_health():
    from fastapi.responses import JSONResponse
    from app.core.health import deep_health

    result = deep_health()
    return JSONResponse(result, status_code=200 if result["status"] == "ok" else 503)


@router.get("/audit", dependencies=[require_role("REVIEWER", "ADMIN", error_code="AUDIT_ACCESS_FORBIDDEN")])
def list_audit(
    db: Db,
    report_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_PAGE)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    """The audit trail. Restricted to reviewers and administrators: it names who did what and when,
    which is exactly the reconnaissance an ordinary viewer should not be handed.
    """
    query = select(AuditEvent)
    if report_id:
        # Filtered in SQL. Applying the limit first and filtering the page afterwards returned an
        # arbitrary subset of one report's history - usually empty once the trail grew past 500
        # rows - while still looking like a complete answer.
        query = query.where(
            or_(
                AuditEvent.entity_id == report_id,
                AuditEvent.details["report_id"].as_string() == report_id,
            )
        )
    events = db.scalars(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit).offset(offset))
    return [{"id": event.id, "actor": event.actor, "action": event.action, "entity_type": event.entity_type, "entity_id": event.entity_id, "request_id": event.request_id, "details": event.details, "created_at": event.created_at} for event in events]
