"""Audit trail writes.

The lowest layer of the service package: it imports no other service module, so every other
module can record an event without creating an import cycle.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditEvent


def audit(db: Session, action: str, entity_type: str, entity_id: str, request_id: str, details: dict | None = None) -> None:
    db.add(AuditEvent(action=action, entity_type=entity_type, entity_id=entity_id, request_id=request_id, details=details or {}))
