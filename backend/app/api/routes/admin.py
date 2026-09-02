"""Operational endpoints: the liveness probe and the audit trail.

Neither belongs to a single report, which is why they sit outside the report-scoped modules.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.domain.models import AuditEvent
from .deps import Db

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "commentary-api", "architecture": {"frontend": "React", "backend": "FastAPI"}}


@router.get("/audit")
def list_audit(db: Db, report_id: str | None = None, limit: int = 100) -> list[dict]:
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(max(limit, 1), 500))
    events = list(db.scalars(query))
    if report_id:
        events = [event for event in events if event.entity_id == report_id or event.details.get("report_id") == report_id]
    return [{"id": event.id, "actor": event.actor, "action": event.action, "entity_type": event.entity_type, "entity_id": event.entity_id, "request_id": event.request_id, "details": event.details, "created_at": event.created_at} for event in events]
