"""Audit trail writes.

The lowest layer of the service package: it imports no other service module, so every other
module can record an event without creating an import cycle.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import current_principal
from ..models import AuditEvent


def audit_actor(override: str | None = None) -> str:
    """Who to attribute an event to.

    Read from the request context rather than passed down through every call site, so that adding
    an audited action cannot silently omit the actor. Work with no request behind it - a standalone
    render, an alembic data fix - is attributed to ``system`` rather than to whoever happened to
    trigger it last.
    """
    if override:
        return override
    caller = current_principal()
    return caller.subject if caller else "system"


def audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str,
    request_id: str,
    details: dict | None = None,
    actor: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor=audit_actor(actor),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=request_id,
            details=details or {},
        )
    )
