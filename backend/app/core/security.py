from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    product_scope: frozenset[str]


class AuthorizationMiddleware(BaseHTTPMiddleware):
    """Local/UAT role enforcement boundary; deployed ENTRA mode requires a bearer token."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(settings.api_prefix) or request.url.path.endswith("/health"):
            return await call_next(request)
        authorization = request.headers.get("Authorization", "")
        if settings.auth_mode == "ENTRA" and not authorization.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error_code": "AUTHENTICATION_REQUIRED", "message": "A Microsoft Entra bearer token is required."})
        role = request.headers.get("X-User-Role", "ADMIN" if settings.auth_mode == "LOCAL" else "VIEWER").upper()
        if role not in {"ADMIN", "EDITOR", "REVIEWER", "VIEWER"}:
            return JSONResponse(status_code=403, content={"error_code": "INVALID_ROLE"})
        if request.method not in {"GET", "HEAD", "OPTIONS"} and role == "VIEWER":
            return JSONResponse(status_code=403, content={"error_code": "WRITE_FORBIDDEN", "message": "Viewer role cannot modify reports."})
        if request.url.path.endswith("/finalize") and request.method == "POST" and role not in {"ADMIN", "REVIEWER"}:
            return JSONResponse(status_code=403, content={"error_code": "FINALIZE_FORBIDDEN", "message": "Reviewer or administrator role is required."})
        scope = frozenset(filter(None, (item.strip() for item in request.headers.get("X-Product-Scope", "*").split(","))))
        request.state.principal = Principal(request.headers.get("X-User-ID", "local-user"), role, scope)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
