"""Microsoft Entra ID bearer-token validation.

``AUTH_MODE=ENTRA`` used to accept any string beginning with ``"Bearer "`` and then read the caller's
role out of a request header, so anyone who could reach the API could name themselves ADMIN. This
module is the real check: signature against the tenant's published JWKS, then audience, issuer and
expiry, then role and product scope taken from *claims* rather than from headers.

Everything here fails closed. A token that cannot be parsed, whose key is unknown, whose algorithm
was not configured, or that carries no recognised role is rejected - there is no permissive fallback,
because a fallback in an authentication path is an authentication bypass.

PyJWT is an optional dependency (``pip install -e "./backend[entra]"``). It is imported lazily so a
LOCAL-mode workstation or a test run does not need it, and :func:`ensure_available` turns a missing
install into a startup failure instead of a 500 on the first authenticated request.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import settings

# Ordered least- to most-privileged. Shared with app.core.security so a claim and a LOCAL header
# resolve through exactly one table.
ROLES: tuple[str, ...] = ("VIEWER", "EDITOR", "REVIEWER", "ADMIN")
UNRESTRICTED_SCOPE = "*"

# A tenant's key document is a few kilobytes. The ceiling stops a compromised or misconfigured
# discovery endpoint from streaming an unbounded body into the process.
_MAX_JWKS_BYTES = 1024 * 1024
# An unknown `kid` triggers at most one out-of-band refresh per interval, so a flood of tokens
# bearing random key ids cannot turn this service into a load generator against the identity
# provider.
_MIN_REFRESH_INTERVAL_SECONDS = 60.0


class TokenError(Exception):
    """A bearer token was rejected. Carries the envelope fields the API replies with."""

    def __init__(self, error_code: str, message: str, fix_hint: str = "", status_code: int = 401) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.fix_hint = fix_hint
        self.status_code = status_code


@dataclass(frozen=True)
class TokenIdentity:
    """The only three things the application is allowed to learn from a token."""

    subject: str
    role: str
    product_scope: frozenset[str]


def ensure_available() -> None:
    """Raise if ENTRA mode cannot actually validate a signature. Called once at startup."""
    _load_pyjwt()


def _load_pyjwt():
    try:
        import jwt  # noqa: PLC0415 - optional dependency, imported on first use
    except ModuleNotFoundError as error:  # pragma: no cover - depends on the install extra
        raise TokenError(
            "AUTH_BACKEND_UNAVAILABLE",
            "AUTH_MODE=ENTRA requires PyJWT with cryptography support, which is not installed.",
            'Install the extra: pip install -e "./backend[entra]".',
            status_code=500,
        ) from error
    return jwt


def _configured_audiences() -> list[str]:
    raw = settings.entra_audience or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


class _SigningKeys:
    """TTL-cached JWKS with a rate-limited refresh for key rollover.

    Entra rotates signing keys without warning, so an unknown ``kid`` is normal rather than
    hostile and must trigger a refetch; the interval guard keeps that from becoming an
    amplification path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._document: dict[str, Any] = {}
        self._fetched_at = 0.0

    def reset(self) -> None:
        """Drop the cache. Used by tests and after a configuration change."""
        with self._lock:
            self._document = {}
            self._fetched_at = 0.0

    def signing_key(self, kid: str):
        jwt = _load_pyjwt()
        document = self._document_for(kid)
        for key in document.get("keys", []):
            if key.get("kid") == kid:
                try:
                    return jwt.PyJWK(key).key
                except Exception as error:  # pragma: no cover - malformed provider document
                    raise TokenError(
                        "TOKEN_KEY_UNUSABLE",
                        "The identity provider published a signing key this service cannot parse.",
                        "Check ENTRA_JWKS_URL points at the tenant's v2.0 discovery keys endpoint.",
                    ) from error
        raise TokenError(
            "TOKEN_KEY_UNKNOWN",
            "The token was signed with a key the configured tenant does not publish.",
            "Confirm ENTRA_TENANT_ID matches the tenant that issued the token.",
        )

    def _document_for(self, kid: str) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            fresh = self._document and now - self._fetched_at < settings.entra_jwks_cache_seconds
            known = fresh and any(key.get("kid") == kid for key in self._document.get("keys", []))
            if known:
                return self._document
            if fresh and now - self._fetched_at < _MIN_REFRESH_INTERVAL_SECONDS:
                return self._document
            document = _fetch_jwks()
            self._document = document
            self._fetched_at = now
            return document


def _fetch_jwks() -> dict[str, Any]:
    url = settings.resolved_entra_jwks_url
    if not url:
        raise TokenError(
            "AUTH_NOT_CONFIGURED",
            "No JWKS endpoint is configured, so token signatures cannot be verified.",
            "Set ENTRA_TENANT_ID (or ENTRA_JWKS_URL).",
            status_code=500,
        )
    if not url.startswith("https://"):
        # Keys fetched over plaintext can be substituted in transit, which forges every identity.
        raise TokenError(
            "AUTH_NOT_CONFIGURED",
            "ENTRA_JWKS_URL must be an https:// endpoint.",
            "Point ENTRA_JWKS_URL at the tenant's https discovery keys endpoint.",
            status_code=500,
        )
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=settings.entra_jwks_timeout_seconds) as response:
            body = response.read(_MAX_JWKS_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise TokenError(
            "AUTH_PROVIDER_UNREACHABLE",
            "The identity provider's signing keys could not be retrieved.",
            "Check outbound network access to login.microsoftonline.com and retry.",
            status_code=503,
        ) from error
    if len(body) > _MAX_JWKS_BYTES:
        raise TokenError(
            "AUTH_PROVIDER_UNREACHABLE",
            "The identity provider returned an implausibly large key document.",
            "Verify ENTRA_JWKS_URL.",
            status_code=503,
        )
    try:
        document = json.loads(body)
    except json.JSONDecodeError as error:
        raise TokenError(
            "AUTH_PROVIDER_UNREACHABLE",
            "The identity provider's key document was not valid JSON.",
            "Verify ENTRA_JWKS_URL.",
            status_code=503,
        ) from error
    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise TokenError(
            "AUTH_PROVIDER_UNREACHABLE",
            "The identity provider's key document did not contain a key set.",
            "Verify ENTRA_JWKS_URL.",
            status_code=503,
        )
    return document


_SIGNING_KEYS = _SigningKeys()


def reset_key_cache() -> None:
    _SIGNING_KEYS.reset()


def verify_bearer_token(token: str) -> TokenIdentity:
    """Validate a bearer token and reduce it to a subject, a role and a product scope."""
    jwt = _load_pyjwt()
    audiences = _configured_audiences()
    issuer = settings.resolved_entra_issuer
    if not audiences or not issuer:
        raise TokenError(
            "AUTH_NOT_CONFIGURED",
            "Token validation is not configured, so no token can be accepted.",
            "Set ENTRA_AUDIENCE and ENTRA_TENANT_ID (or ENTRA_ISSUER).",
            status_code=500,
        )
    try:
        header = jwt.get_unverified_header(token)
    except Exception as error:
        raise TokenError(
            "TOKEN_MALFORMED",
            "The Authorization header did not contain a readable JSON Web Token.",
            "Send the access token issued for this API, not an ID token or an opaque string.",
        ) from error
    algorithm = str(header.get("alg", "")).upper()
    if algorithm not in settings.entra_allowed_algorithms:
        # Pinning the algorithm is what stops "alg": "none" and HS256-signed-with-the-public-key.
        raise TokenError(
            "TOKEN_ALGORITHM_REJECTED",
            f"Tokens signed with {algorithm or 'an unspecified algorithm'} are not accepted.",
            f"Expected one of: {', '.join(settings.entra_allowed_algorithms)}.",
        )
    kid = header.get("kid")
    if not kid:
        raise TokenError(
            "TOKEN_MALFORMED",
            "The token header carries no key id, so its signing key cannot be located.",
            "Send an access token issued by Microsoft Entra ID.",
        )
    key = _SIGNING_KEYS.signing_key(str(kid))
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=list(settings.entra_allowed_algorithms),
            audience=audiences,
            issuer=issuer,
            leeway=settings.entra_leeway_seconds,
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as error:
        raise TokenError(
            "TOKEN_EXPIRED", "The access token has expired.", "Acquire a fresh token and retry."
        ) from error
    except jwt.InvalidAudienceError as error:
        raise TokenError(
            "TOKEN_AUDIENCE_REJECTED",
            "The access token was issued for a different application.",
            "Request a token whose audience is this API's application ID URI.",
        ) from error
    except jwt.InvalidIssuerError as error:
        raise TokenError(
            "TOKEN_ISSUER_REJECTED",
            "The access token was issued by a different tenant.",
            "Sign in against the tenant configured in ENTRA_TENANT_ID.",
        ) from error
    except jwt.InvalidTokenError as error:
        raise TokenError(
            "TOKEN_INVALID",
            "The access token failed validation.",
            "Acquire a fresh token from the configured tenant and retry.",
        ) from error
    return TokenIdentity(
        subject=_resolve_subject(claims),
        role=_resolve_role(claims),
        product_scope=_resolve_product_scope(claims),
    )


def _claim_values(claims: dict[str, Any], name: str) -> list[str]:
    """Read a claim that Entra may emit as a list, a space-delimited string or a CSV string."""
    raw = claims.get(name)
    if raw is None:
        return []
    if isinstance(raw, str):
        return [item for item in raw.replace(",", " ").split() if item]
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [str(raw).strip()]


def _resolve_subject(claims: dict[str, Any]) -> str:
    # `oid` is the immutable per-tenant object id; `sub` is pairwise and rotates per application,
    # so `oid` is the one an audit trail can still resolve to a person months later.
    for name in ("oid", "sub", "appid", "azp"):
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise TokenError(
        "TOKEN_SUBJECT_MISSING",
        "The access token identifies no subject, so no action could be attributed to a caller.",
        "Use an access token that carries an `oid` or `sub` claim.",
    )


def _resolve_role(claims: dict[str, Any]) -> str:
    granted = {value.strip().upper() for value in _claim_values(claims, settings.entra_role_claim)}
    # Most privileged wins when several app roles are assigned to the same principal.
    recognised = [role for role in ROLES if role in granted]
    if not recognised:
        raise TokenError(
            "ROLE_NOT_ASSIGNED",
            "The signed-in account has no application role for this API.",
            f"Assign one of {', '.join(ROLES)} in Entra, or point ENTRA_ROLE_CLAIM at the claim that carries it.",
            status_code=403,
        )
    return recognised[-1]


def _resolve_product_scope(claims: dict[str, Any]) -> frozenset[str]:
    claim_name = settings.entra_product_scope_claim
    if not claim_name:
        # Deployments that do not model product scope in the directory opt out explicitly by
        # clearing ENTRA_PRODUCT_SCOPE_CLAIM. Silence is not treated as consent.
        return frozenset({UNRESTRICTED_SCOPE})
    values = _claim_values(claims, claim_name)
    if not values:
        raise TokenError(
            "PRODUCT_SCOPE_NOT_ASSIGNED",
            "The access token carries no product scope, so no fund could be shown.",
            f"Emit a `{claim_name}` claim listing the product codes (or `*`), "
            "or clear ENTRA_PRODUCT_SCOPE_CLAIM if scope is not modelled in the directory.",
            status_code=403,
        )
    return frozenset(value.upper() for value in values)
