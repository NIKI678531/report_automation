"""The authorization boundary: who the caller is, and what that lets them do.

Two identity sources, one enforcement path. In ``LOCAL`` mode the caller *asserts* an identity
through ``X-User-Role`` / ``X-User-ID`` / ``X-Product-Scope`` headers, which is fine on a
workstation and worthless as security. In ``ENTRA`` mode the identity is *proved* by a signed
access token (see :mod:`app.core.entra`) and headers are ignored entirely - otherwise a caller
could authenticate as a viewer and then simply claim ``X-User-Role: ADMIN``.

This is a pure ASGI middleware rather than a ``BaseHTTPMiddleware``: the downstream application then
runs inside this middleware's own context, so the :data:`current_principal` context variable is
visible to the service layer and the audit trail without threading a principal argument through
every function signature.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import settings
from .entra import ROLES, UNRESTRICTED_SCOPE, TokenError, TokenIdentity, verify_bearer_token

_ROLE_RANK = {name: rank for rank, name in enumerate(ROLES)}
#: Methods that cannot change state, and so are the only ones a VIEWER may use.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Roles that may move a report from IN_REVIEW to FINALIZED.
FINALIZE_ROLES = frozenset({"REVIEWER", "ADMIN"})

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}

#: JSON responses and file downloads need no resources of their own.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
#: The report preview is a self-contained document - inline styles, a data: logo, data: CJK fonts
#: and no script at all - so it gets a policy that permits exactly that and nothing else. A blanket
#: `default-src 'none'` here would render the preview unstyled and unreadable, and the looser
#: product-UI policy would permit script the report never legitimately contains.
_DOCUMENT_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "script-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


@dataclass(frozen=True)
class Principal:
    """An authenticated caller, reduced to what authorization actually needs."""

    subject: str
    role: str
    product_scope: frozenset[str]

    @property
    def is_unrestricted(self) -> bool:
        return UNRESTRICTED_SCOPE in self.product_scope

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    def has_at_least(self, role: str) -> bool:
        return _ROLE_RANK.get(self.role, -1) >= _ROLE_RANK[role]

    def may_write(self) -> bool:
        return self.role != "VIEWER"

    def may_finalize(self) -> bool:
        return self.role in FINALIZE_ROLES

    def may_access_product(self, product_code: str | None) -> bool:
        """Product scope gates *rows*, not endpoints; a report with no product is visible to all."""
        if self.is_unrestricted or not product_code:
            return True
        return product_code.upper() in self.product_scope


#: A caller for work that no request initiated - Celery tasks, CLI imports, migrations.
SYSTEM_PRINCIPAL = Principal(subject="system", role="ADMIN", product_scope=frozenset({UNRESTRICTED_SCOPE}))

_current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)


def current_principal() -> Principal | None:
    """The caller for the request being served, or ``None`` outside a request."""
    return _current_principal.get()


def bind_principal(principal: Principal):
    """Bind a principal for the current context. Returns the token to pass to :func:`reset_principal`."""
    return _current_principal.set(principal)


def reset_principal(token) -> None:
    _current_principal.reset(token)


def _local_principal(headers: Headers) -> Principal | TokenError:
    role = headers.get("X-User-Role", "ADMIN").strip().upper()
    if role not in _ROLE_RANK:
        return TokenError(
            "INVALID_ROLE",
            f"{role!r} is not a role this system recognises.",
            f"Send X-User-Role as one of: {', '.join(ROLES)}.",
            status_code=403,
        )
    scope = frozenset(
        item.strip().upper() for item in headers.get("X-Product-Scope", UNRESTRICTED_SCOPE).split(",") if item.strip()
    )
    subject = headers.get("X-User-ID", "local-user").strip() or "local-user"
    return Principal(subject=subject, role=role, product_scope=scope or frozenset({UNRESTRICTED_SCOPE}))


def _entra_principal(headers: Headers) -> Principal | TokenError:
    authorization = headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return TokenError(
            "AUTHENTICATION_REQUIRED",
            "A Microsoft Entra bearer token is required.",
            "Send `Authorization: Bearer <access token>`.",
        )
    try:
        identity: TokenIdentity = verify_bearer_token(token.strip())
    except TokenError as error:
        return error
    return Principal(subject=identity.subject, role=identity.role, product_scope=identity.product_scope)


def resolve_principal(headers: Headers) -> Principal | TokenError:
    """Identify the caller using the configured authentication mode."""
    return _local_principal(headers) if settings.is_local_auth else _entra_principal(headers)


def _denial(error_code: str, message: str, fix_hint: str, status_code: int, request_id: str | None) -> dict:
    return {
        "error_code": error_code,
        "message": message,
        "severity": "BLOCKING",
        "fix_hint": fix_hint,
        "request_id": request_id,
    }


class AuthorizationMiddleware:
    """Authenticate every API request, then apply the role rules that hold for all of them.

    Endpoint-specific rules (ADMIN-only catalog writes, product-scope row filtering) live with the
    endpoints in ``app.api.routes.deps``; what stays here is what is true everywhere: a VIEWER never
    writes, and only a REVIEWER or ADMIN finalizes.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()
        # CORS preflight carries no credentials by design; rejecting it would break the browser
        # client before the real, authenticated request is ever sent.
        if not path.startswith(settings.api_prefix) or method == "OPTIONS":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        request_id = headers.get("X-Request-ID")
        # Exact match: `endswith("/health")` would also exempt any future path ending in those
        # characters, e.g. /api/v1/reports/{id}/health.
        if path.rstrip("/") == f"{settings.api_prefix}/health":
            await self._serve(scope, receive, send)
            return

        outcome = resolve_principal(headers)
        if isinstance(outcome, TokenError):
            await self._deny(
                scope, receive, send,
                _denial(outcome.error_code, outcome.message, outcome.fix_hint, outcome.status_code, request_id),
                outcome.status_code,
            )
            return
        principal = outcome
        if method not in SAFE_METHODS and not principal.may_write():
            await self._deny(
                scope, receive, send,
                _denial(
                    "WRITE_FORBIDDEN",
                    "Viewer role cannot modify reports.",
                    "Ask an administrator for the EDITOR role.",
                    403, request_id,
                ),
                403,
            )
            return
        if method == "POST" and path.rstrip("/").endswith("/finalize") and not principal.may_finalize():
            await self._deny(
                scope, receive, send,
                _denial(
                    "FINALIZE_FORBIDDEN",
                    "Reviewer or administrator role is required.",
                    "Ask a reviewer to complete the release gate.",
                    403, request_id,
                ),
                403,
            )
            return

        scope.setdefault("state", {})["principal"] = principal
        token = bind_principal(principal)
        try:
            await self._serve(scope, receive, send)
        finally:
            reset_principal(token)

    async def _serve(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, _with_security_headers(send))

    async def _deny(self, scope: Scope, receive: Receive, send: Send, body: dict, status_code: int) -> None:
        # Built here rather than raised: this middleware sits outside FastAPI's exception handlers,
        # so the structured envelope has to be produced explicitly to match every other error.
        payload = json.dumps(body).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
        if status_code == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        headers.extend((key.lower().encode(), value.encode()) for key, value in _security_headers_for("application/json").items())
        await send({"type": "http.response.start", "status": status_code, "headers": headers})
        await send({"type": "http.response.body", "body": payload})


def _security_headers_for(content_type: str) -> dict[str, str]:
    csp = _DOCUMENT_CSP if content_type.split(";", 1)[0].strip().casefold() == "text/html" else _API_CSP
    return {**SECURITY_HEADERS, "Content-Security-Policy": csp}


def _with_security_headers(send: Send) -> Send:
    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            existing = {key.lower() for key, _ in headers}
            content_type = next((value.decode("latin-1") for key, value in headers if key.lower() == b"content-type"), "")
            headers.extend(
                (key.lower().encode(), value.encode())
                for key, value in _security_headers_for(content_type).items()
                if key.lower().encode() not in existing
            )
            message["headers"] = headers
        await send(message)

    return wrapped
