"""Dependencies shared by every route module."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Principal

Db = Annotated[Session, Depends(get_db)]


def request_id(value: Annotated[str | None, Header(alias="X-Request-ID")] = None) -> str:
    """Correlation id for the audit trail, generated when the caller does not supply one."""
    return value or str(uuid4())


RequestId = Annotated[str, Depends(request_id)]


def principal(request: Request) -> Principal:
    """The authenticated caller, placed on the request by ``AuthorizationMiddleware``."""
    caller: Principal | None = getattr(request.state, "principal", None)
    if caller is None:  # pragma: no cover - only reachable if the middleware is removed
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTHENTICATION_REQUIRED",
                "message": "The request was not authenticated.",
                "fix_hint": "Send credentials for the configured AUTH_MODE.",
            },
        )
    return caller


CurrentPrincipal = Annotated[Principal, Depends(principal)]


def require_role(*roles: str, error_code: str = "ROLE_FORBIDDEN"):
    """Restrict an endpoint to the named roles.

    The middleware enforces what is true of every request - a viewer never writes, only a reviewer
    finalizes. Per-endpoint rules belong here instead, next to the endpoint they describe, so that
    reading the route signature tells you who may call it. As a dependency the check also runs
    *before* the body, so an unauthorized upload is rejected without being read off the wire.
    """
    allowed = frozenset(role.upper() for role in roles)
    message = f"This action requires one of: {', '.join(sorted(allowed))}."

    def dependency(caller: CurrentPrincipal) -> Principal:
        if caller.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": error_code,
                    "message": message,
                    "fix_hint": "Ask an administrator to grant the required role.",
                },
            )
        return caller

    return Depends(dependency)


def require_product_access(caller: Principal, product_code: str | None) -> None:
    """Reject a caller whose token does not cover this product.

    Raised as 404 rather than 403 on purpose: a caller outside the scope should not be able to
    learn that a fund's report exists by comparing status codes.
    """
    if not caller.may_access_product(product_code):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "REPORT_NOT_FOUND",
                "message": "No report with that identifier is available.",
                "fix_hint": "Check the report id, or ask for access to this product.",
            },
        )
