"""Dependencies shared by every route module."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.database import get_db

Db = Annotated[Session, Depends(get_db)]


def request_id(value: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> str:
    """Correlation id for the audit trail, generated when the caller does not supply one."""
    return value or str(uuid4())


RequestId = Annotated[str, Depends(request_id)]
