"""The authorization boundary, exercised end to end.

The suite is organised by the property being defended rather than by module, because most of these
rules span the middleware, a route dependency and the service layer at once: product scope, for
instance, is decided from a token claim, applied as a SQL filter in ``list_reports`` and re-applied
as a 404 in ``service.get_report``. A test that only reached one of the three would pass while the
other two leaked.

ENTRA-mode signature tests need PyJWT (``pip install -e "./backend[entra]"``) and skip without it.
The tests that prove ENTRA *refuses* an unauthenticated caller do not, and always run: those are
the ones that would matter most if the extra were ever dropped from the image.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time

import pytest

from app.core import entra
from app.core.config import ConfigurationError, DEFAULT_DOWNLOAD_SECRET, Settings, settings
from app.core.security import _API_CSP, _DOCUMENT_CSP, Principal
from app.core import download_signing
from app.main import create_app

ISSUER = "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000/v2.0"
AUDIENCE = "api://commentary-test"
KEY_ID = "test-signing-key"


@pytest.fixture()
def translation_job_context(client, monkeypatch):
    from app.api.routes import reports as routes

    monkeypatch.setattr(settings, "translation_provider", "OPENAI_COMPATIBLE")
    monkeypatch.setattr(settings, "translation_base_url", "https://approved.example/v1")
    monkeypatch.setattr(settings, "translation_model", "approved-model")
    monkeypatch.setattr(settings, "translation_api_key", "test-only")
    monkeypatch.setattr(routes, "dispatch_translation", lambda *_: None)
    source = client.post("/api/v1/reports", json={"report_date": "2026-08-31"}).json()
    target = client.post(f"/api/v1/reports/{source['id']}/language-variants", json={"language_mode": "ZH_HANS", "source_document_version": 1}).json()
    return source, target, f"/api/v1/reports/{source['id']}/language-variants/{target['id']}/translations", {"source_document_version": 1, "target_document_version": 1}


def test_translation_roles_scope_and_idempotency_are_isolated(client, translation_job_context):
    source, target, url, command = translation_job_context
    assert client.post(url, json=command, headers={"X-User-Role": "VIEWER", "Idempotency-Key": "key"}).status_code == 403
    assert client.post(url, json=command, headers={"X-Product-Scope": "3037", "Idempotency-Key": "key"}).status_code == 404
    first = client.post(url, json=command, headers={"X-User-ID": "alice", "Idempotency-Key": "key"}).json()
    second = client.post(url, json=command, headers={"X-User-ID": "bob", "Idempotency-Key": "key"}).json()
    assert first["id"] != second["id"]
    assert client.get(first["status_url"], headers={"X-Product-Scope": "3037"}).status_code == 404
    assert client.get(f"/api/v1/reports/{source['id']}/translation-jobs/{first['id']}").status_code == 404
    conflict = client.post(url, json={**command, "target_document_version": 2}, headers={"X-User-ID": "alice", "Idempotency-Key": "key"})
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_translation_does_not_accept_provider_or_prompt_from_request(client, translation_job_context):
    _, _, url, command = translation_job_context
    response = client.post(url, json={**command, "base_url": "https://unapproved.example", "prompt": "override"}, headers={"Idempotency-Key": "key"})
    assert response.status_code == 422


@pytest.mark.parametrize("setting,value", [("translation_base_url", "http://approved.example"), ("translation_base_url", "https://user:password@approved.example"), ("translation_base_url", "https://approved.example?token=secret"), ("translation_model", ""), ("translation_api_key", ""), ("translation_provider", "UNKNOWN"), ("translation_timeout_seconds", 0)])
def test_translation_configuration_is_fail_closed(setting, value):
    configured = Settings(translation_provider="OPENAI_COMPATIBLE", translation_base_url="https://approved.example/v1", translation_model="test", translation_api_key="test-only")
    setattr(configured, setting, value)
    assert configured.translation_problems()
    configured.auth_mode = "ENTRA"
    assert any("TRANSLATION_" in problem for problem in configured.deployment_problems())


def test_translation_target_finalized_while_queued_is_not_changed(client, translation_job_context):
    from app.core.database import get_db
    from app.domain.service.translations import execute_translation

    _, target, url, command = translation_job_context
    job = client.post(url, json=command, headers={"Idempotency-Key": "key"}).json()
    assert client.post(f"/api/v1/reports/{target['id']}/finalize", json={"version": 1}).status_code == 200
    with next(client.app.dependency_overrides[get_db]()) as db:
        assert execute_translation(db, job["id"]) == "FAILED"
    current = client.get(f"/api/v1/reports/{target['id']}").json()
    assert current["status"] == "FINALIZED"
    assert current["latest_document"]["version"] == 1


# --------------------------------------------------------------------------------------------
# LOCAL mode: the role a caller asserts, and what it lets them do
# --------------------------------------------------------------------------------------------


def test_viewer_cannot_write_but_can_read(client):
    denied = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}, headers={"X-User-Role": "VIEWER"})
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "WRITE_FORBIDDEN"
    allowed = client.get("/api/v1/reports", headers={"X-User-Role": "VIEWER"})
    assert allowed.status_code == 200
    assert allowed.headers["x-content-type-options"] == "nosniff"


def test_editor_cannot_finalize(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 1}, headers={"X-User-Role": "EDITOR"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "FINALIZE_FORBIDDEN"


def test_reviewer_can_finalize(client):
    """The negative test above only proves the gate closes; this proves it also opens."""
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": 1}, headers={"X-User-Role": "REVIEWER"})
    assert response.status_code == 200
    assert response.json()["status"] == "FINALIZED"


def test_an_unrecognised_role_is_refused_rather_than_defaulted(client):
    """A typo in a role must not silently fall back to a working identity."""
    response = client.get("/api/v1/reports", headers={"X-User-Role": "SUPERUSER"})
    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "INVALID_ROLE"
    assert "VIEWER" in body["fix_hint"]


def test_role_matching_ignores_case(client):
    response = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}, headers={"X-User-Role": "viewer"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "WRITE_FORBIDDEN"


# --------------------------------------------------------------------------------------------
# Product scope: rows, not endpoints
# --------------------------------------------------------------------------------------------


def _two_reports(client) -> tuple[str, str]:
    hstech = client.post("/api/v1/reports", json={"report_date": "2026-06-30", "product_code": "3033"}).json()["id"]
    hsi = client.post("/api/v1/reports", json={"report_date": "2026-06-30", "product_code": "3037"}).json()["id"]
    return hstech, hsi


def test_product_scope_filters_the_report_list(client):
    _two_reports(client)
    scoped = client.get("/api/v1/reports", headers={"X-Product-Scope": "3037"})
    assert scoped.status_code == 200
    assert {item["product_code"] for item in scoped.json()} == {"3037"}


def test_out_of_scope_report_answers_404_not_403(client):
    """A 403 would confirm the report exists, letting a caller enumerate funds by probing ids."""
    hstech, _ = _two_reports(client)
    response = client.get(f"/api/v1/reports/{hstech}", headers={"X-Product-Scope": "3037"})
    assert response.status_code == 404
    assert response.json()["error_code"] == "REPORT_NOT_FOUND"


def test_out_of_scope_report_cannot_be_written_either(client):
    hstech, _ = _two_reports(client)
    response = client.post(
        f"/api/v1/reports/{hstech}/finalize",
        json={"version": 1},
        headers={"X-User-Role": "REVIEWER", "X-Product-Scope": "3037"},
    )
    assert response.status_code == 404


def test_unrestricted_scope_sees_every_product(client):
    _two_reports(client)
    everything = client.get("/api/v1/reports", headers={"X-Product-Scope": "*"})
    assert {item["product_code"] for item in everything.json()} == {"3033", "3037"}


def test_product_scope_is_matched_case_insensitively():
    caller = Principal(subject="s", role="VIEWER", product_scope=frozenset({"3033"}))
    assert caller.may_access_product("3033")
    assert caller.may_access_product("3033".lower())
    assert not caller.may_access_product("3037")
    # A report that belongs to no product is a system-level row, not a hidden one.
    assert caller.may_access_product(None)


# --------------------------------------------------------------------------------------------
# Which paths skip authentication
# --------------------------------------------------------------------------------------------


def test_health_needs_no_identity(client):
    """The container healthcheck calls this with no headers at all."""
    response = client.get("/api/v1/health", headers={"X-User-Role": "NOT-A-ROLE"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_only_the_exact_health_path_is_exempt(client):
    """`endswith("/health")` would have exempted every report-scoped path ending the same way."""
    response = client.get("/api/v1/reports/any-id/health", headers={"X-User-Role": "NOT-A-ROLE"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "INVALID_ROLE"


def test_non_api_paths_are_not_intercepted(client):
    """The OpenAPI document and docs page are served without an identity; they are not the API."""
    assert client.get("/docs").status_code == 200


# --------------------------------------------------------------------------------------------
# Response headers
# --------------------------------------------------------------------------------------------


def test_json_responses_deny_every_resource_type(client):
    response = client.get("/api/v1/reports")
    assert response.headers["content-security-policy"] == _API_CSP
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"


def test_the_preview_document_gets_a_policy_it_can_still_render_under(client):
    """The report preview is self-contained: inline styles, data: fonts and images, no script.

    `default-src 'none'` alone would deliver it unstyled and unreadable, which is why the policy is
    chosen per content type rather than set once for the whole API.
    """
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.get(f"/api/v1/reports/{report['id']}/preview")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    policy = response.headers["content-security-policy"]
    assert policy == _DOCUMENT_CSP
    assert "style-src 'unsafe-inline'" in policy
    assert "img-src data:" in policy
    assert "font-src data:" in policy
    # Whatever else it may load, the preview must never execute script or be framed.
    assert "script-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy


def test_denials_carry_the_same_headers_as_successes(client):
    """The middleware answers outside FastAPI's handlers, so it has to add these itself."""
    response = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}, headers={"X-User-Role": "VIEWER"})
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == _API_CSP


def test_a_denial_echoes_the_request_id_for_correlation(client):
    response = client.post(
        "/api/v1/reports",
        json={"report_date": "2026-06-30"},
        headers={"X-User-Role": "VIEWER", "X-Request-ID": "req-42"},
    )
    body = response.json()
    assert body["request_id"] == "req-42"
    assert set(body) >= {"error_code", "message", "severity", "fix_hint", "request_id"}


# --------------------------------------------------------------------------------------------
# The audit trail
# --------------------------------------------------------------------------------------------


def test_audit_trail_is_closed_to_editors(client):
    """It names who did what and when, which is reconnaissance an editor has no need for."""
    denied = client.get("/api/v1/audit", headers={"X-User-Role": "EDITOR"})
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "AUDIT_ACCESS_FORBIDDEN"
    assert client.get("/api/v1/audit", headers={"X-User-Role": "REVIEWER"}).status_code == 200


def test_audit_records_the_caller_not_a_placeholder(client):
    """Every event used to be attributed to "system", which makes the trail unusable as evidence."""
    report = client.post(
        "/api/v1/reports",
        json={"report_date": "2026-06-30"},
        headers={"X-User-ID": "alice@example.com"},
    ).json()
    events = client.get("/api/v1/audit", params={"report_id": report["id"]}).json()
    assert events
    assert {event["actor"] for event in events} == {"alice@example.com"}


def test_audit_page_size_is_bounded(client):
    """An unbounded limit is a way to pull the whole trail in one request."""
    assert client.get("/api/v1/audit", params={"limit": 501}).status_code == 422
    assert client.get("/api/v1/audit", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/audit", params={"offset": -1}).status_code == 422
    assert client.get("/api/v1/audit", params={"limit": 500}).status_code == 200


# --------------------------------------------------------------------------------------------
# Endpoint-specific role gates
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "error_code"),
    [
        ("/api/v1/products/import", "PRODUCT_ADMIN_REQUIRED"),
        ("/api/v1/industry-master/import", "INDUSTRY_ADMIN_REQUIRED"),
    ],
)
def test_catalog_imports_require_an_administrator(client, path, error_code):
    response = client.post(
        path,
        files={"file": ("catalog.csv", b"product_code\n3033\n", "text/csv")},
        data={"taxonomy_version": "v1", "effective_from": "2026-01-01"},
        headers={"X-User-Role": "REVIEWER"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == error_code


def test_mapping_profile_creation_requires_an_administrator(client):
    """A mapping profile decides how an uploaded column becomes a reported number."""
    response = client.post("/api/v1/mapping-profiles", json={}, headers={"X-User-Role": "REVIEWER"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "MAPPING_ADMIN_REQUIRED"


# --------------------------------------------------------------------------------------------
# Upload ceilings
# --------------------------------------------------------------------------------------------


def test_oversized_upload_is_refused_through_the_error_envelope(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_max_bytes", 1024)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        files={"file": ("big.csv", b"x" * 4096, "text/csv")},
        data={"dataset_type": "index_constituents"},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error_code"] == "FILE_TOO_LARGE"
    assert body["fix_hint"]


def test_batch_upload_refuses_too_many_files(client, monkeypatch):
    monkeypatch.setattr(settings, "upload_batch_max_files", 2)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(
        f"/api/v1/reports/{report['id']}/import-batches",
        files=[("files", (f"f{index}.csv", b"a,b\n1,2\n", "text/csv")) for index in range(3)],
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == "BATCH_FILE_LIMIT"


def test_batch_upload_refuses_an_oversized_total(client, monkeypatch):
    """Each file can be within the per-file limit while the batch as a whole is not."""
    monkeypatch.setattr(settings, "upload_batch_max_bytes", 1024)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(
        f"/api/v1/reports/{report['id']}/import-batches",
        files=[("files", (f"f{index}.csv", b"x" * 800, "text/csv")) for index in range(2)],
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == "BATCH_TOO_LARGE"


# --------------------------------------------------------------------------------------------
# Signed download grants
# --------------------------------------------------------------------------------------------


def test_a_download_signature_is_bound_to_one_caller_and_one_deadline():
    expires = int(time.time()) + 300
    signature = download_signing.sign("artifact-1", "alice", expires)
    assert download_signing.verify("artifact-1", "alice", expires, signature)
    # A link copied to a colleague is not a second grant.
    assert not download_signing.verify("artifact-1", "bob", expires, signature)
    # Nor does it unlock a different artifact.
    assert not download_signing.verify("artifact-2", "alice", expires, signature)
    # Nor can the deadline be pushed out by editing the query string.
    assert not download_signing.verify("artifact-1", "alice", expires + 60, signature)


def test_an_expired_download_signature_is_refused():
    expired = int(time.time()) - 1
    assert not download_signing.verify("artifact-1", "alice", expired, download_signing.sign("artifact-1", "alice", expired))


def test_a_tampered_download_signature_is_refused():
    expires = int(time.time()) + 300
    signature = download_signing.sign("artifact-1", "alice", expires)
    tampered = ("0" if signature[0] != "0" else "1") + signature[1:]
    assert not download_signing.verify("artifact-1", "alice", expires, tampered)


# --------------------------------------------------------------------------------------------
# Untrusted content that reaches a rendered page
# --------------------------------------------------------------------------------------------


def test_report_templates_escape_by_default():
    """`select_autoescape(["html", "xml"])` matched on the filename suffix, and "3033.html.j2"
    does not end in ".html" - so autoescaping evaluated to False and every {{ }} in the report
    went out raw. This asserts the property directly rather than the constructor argument.
    """
    from app.rendering.html import env

    assert env.autoescape is True
    rendered = env.from_string("{{ value }}").render(value='<script>alert("x")</script>')
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_a_fund_name_from_the_catalog_cannot_inject_markup(client, monkeypatch):
    from app.rendering.html import env

    rendered = env.from_string("<h1>{{ name }}</h1>").render(name='CSOP" onload="alert(1)')
    assert 'onload="alert(1)' not in rendered


def test_a_news_citation_must_be_a_web_address(client):
    """The review UI links these out; `javascript:` would run on the analyst's click."""
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    for hostile in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "file:///etc/passwd"):
        response = client.post(
            f"/api/v1/reports/{report['id']}/news/candidates",
            json={
                "source_name": "Example",
                "source_url": hostile,
                "published_at": "2026-06-01T00:00:00Z",
                "title": "t",
                "summary": "s",
            },
        )
        assert response.status_code == 422, hostile
        assert response.json()["error_code"] == "REQUEST_INVALID"


# --------------------------------------------------------------------------------------------
# ENTRA mode
# --------------------------------------------------------------------------------------------


@pytest.fixture()
def entra_settings(monkeypatch):
    """Switch the running app to ENTRA without rebuilding it.

    ``resolve_principal`` reads the mode per request, so flipping the setting after the client is
    constructed exercises exactly the code a deployed process runs.
    """
    monkeypatch.setattr(settings, "auth_mode", "ENTRA")
    monkeypatch.setattr(settings, "entra_audience", AUDIENCE)
    monkeypatch.setattr(settings, "entra_issuer", ISSUER)
    monkeypatch.setattr(settings, "entra_role_claim", "roles")
    monkeypatch.setattr(settings, "entra_product_scope_claim", "product_scope")
    monkeypatch.setattr(settings, "entra_allowed_algorithms", ("RS256",))
    entra.reset_key_cache()
    yield
    entra.reset_key_cache()


def test_entra_refuses_a_request_with_no_token(client, entra_settings):
    response = client.get("/api/v1/reports")
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHENTICATION_REQUIRED"
    # Without this header a browser client cannot tell "not signed in" from "forbidden".
    assert response.headers["www-authenticate"] == "Bearer"


def test_entra_ignores_the_local_role_header(client, entra_settings):
    """The whole point of the mode: an unauthenticated caller cannot name themselves ADMIN."""
    response = client.get(
        "/api/v1/reports",
        headers={"X-User-Role": "ADMIN", "X-User-ID": "attacker", "X-Product-Scope": "*"},
    )
    assert response.status_code == 401


def test_entra_refuses_a_non_bearer_authorization_header(client, entra_settings):
    for header in ("Basic dXNlcjpwYXNz", "Bearer", "Bearer    ", "token abc"):
        response = client.get("/api/v1/reports", headers={"Authorization": header})
        assert response.status_code == 401, header


def test_entra_still_serves_the_health_probe(client, entra_settings):
    """A liveness probe holds no token, so an ENTRA deployment would never come up healthy."""
    assert client.get("/api/v1/health").status_code == 200


# --- signature validation; needs the [entra] extra -------------------------------------------


def _crypto():
    pytest.importorskip("jwt", reason='requires the extra: pip install -e "./backend[entra]"')
    pytest.importorskip("cryptography", reason='requires the extra: pip install -e "./backend[entra]"')
    import jwt

    return jwt


_KEYS: dict[str, object] = {}


def _private_key():
    if "private" not in _KEYS:
        from cryptography.hazmat.primitives.asymmetric import rsa

        _KEYS["private"] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _KEYS["private"]


def _jwks(jwt, kid: str = KEY_ID) -> dict:
    document = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_private_key().public_key()))
    return {"keys": [{**document, "kid": kid, "use": "sig", "alg": "RS256"}]}


def _claims(**overrides) -> dict:
    now = int(time.time())
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + 600,
        "oid": "11111111-2222-3333-4444-555555555555",
        "roles": ["EDITOR"],
        "product_scope": ["3033"],
        **overrides,
    }


@pytest.fixture()
def signed(monkeypatch, entra_settings):
    """Mint tokens against a key the (stubbed) tenant publishes."""
    jwt = _crypto()
    monkeypatch.setattr(entra, "_fetch_jwks", lambda: _jwks(jwt))
    entra.reset_key_cache()

    def mint(claims: dict | None = None, *, kid: str = KEY_ID, key=None, algorithm: str = "RS256") -> str:
        return jwt.encode(
            claims if claims is not None else _claims(),
            key if key is not None else _private_key(),
            algorithm=algorithm,
            headers={"kid": kid},
        )

    return mint


def test_a_valid_token_authenticates_and_carries_its_role(client, signed):
    token = signed()
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/reports", headers=headers).status_code == 200
    # EDITOR writes but does not finalize, taken from the claim rather than a header.
    created = client.post("/api/v1/reports", json={"report_date": "2026-06-30", "product_code": "3033"}, headers=headers)
    assert created.status_code == 201
    finalize = client.post(f"/api/v1/reports/{created.json()['id']}/finalize", json={"version": 1}, headers=headers)
    assert finalize.status_code == 403
    assert finalize.json()["error_code"] == "FINALIZE_FORBIDDEN"


def test_the_audit_actor_comes_from_the_token_subject(client, signed):
    headers = {"Authorization": f"Bearer {signed()}"}
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30", "product_code": "3033"}, headers=headers).json()
    admin = {"Authorization": f"Bearer {signed(_claims(roles=['ADMIN'], product_scope=['*']))}"}
    events = client.get("/api/v1/audit", params={"report_id": report["id"]}, headers=admin).json()
    assert {event["actor"] for event in events} == {"11111111-2222-3333-4444-555555555555"}


def test_the_immutable_object_id_is_preferred_over_the_pairwise_subject(client, signed):
    """`sub` is per-application and rotates; `oid` is what still resolves to a person later."""
    headers = {"Authorization": f"Bearer {signed(_claims(sub='pairwise-value'))}"}
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30", "product_code": "3033"}, headers=headers).json()
    admin = {"Authorization": f"Bearer {signed(_claims(roles=['ADMIN'], product_scope=['*']))}"}
    events = client.get("/api/v1/audit", params={"report_id": report["id"]}, headers=admin).json()
    assert "pairwise-value" not in {event["actor"] for event in events}


def test_an_expired_token_is_refused(client, signed):
    stale = int(time.time()) - 7200
    token = signed(_claims(iat=stale, nbf=stale, exp=stale + 60))
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TOKEN_EXPIRED"


def test_a_token_for_another_application_is_refused(client, signed):
    """An access token for a different API in the same tenant is signed by the same key."""
    token = signed(_claims(aud="api://some-other-service"))
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TOKEN_AUDIENCE_REJECTED"


def test_a_token_from_another_tenant_is_refused(client, signed):
    token = signed(_claims(iss="https://login.microsoftonline.com/someone-else/v2.0"))
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TOKEN_ISSUER_REJECTED"


def test_a_tampered_payload_is_refused(client, signed):
    header, payload, signature = signed().split(".")
    forged = base64.urlsafe_b64encode(json.dumps(_claims(roles=["ADMIN"])).encode()).rstrip(b"=").decode()
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {header}.{forged}.{signature}"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TOKEN_INVALID"


def test_a_symmetric_algorithm_is_refused(client, signed):
    """Otherwise the tenant's *public* key doubles as an HMAC secret anyone can sign with."""
    token = signed(key="not-a-real-secret-but-long-enough-for-hmac", algorithm="HS256")
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TOKEN_ALGORITHM_REJECTED"


def test_an_unsecured_token_is_refused(client, signed):
    """`alg: none` is a token that validates against nothing."""

    def segment(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    token = f"{segment({'alg': 'none', 'typ': 'JWT', 'kid': KEY_ID})}.{segment(_claims(roles=['ADMIN']))}."
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TOKEN_ALGORITHM_REJECTED"


def test_a_token_signed_with_an_unpublished_key_is_refused(client, signed):
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {signed(kid='rotated-away')}"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TOKEN_KEY_UNKNOWN"


def test_a_string_that_is_not_a_token_is_refused(client, signed):
    response = client.get("/api/v1/reports", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TOKEN_MALFORMED"


def test_an_account_with_no_application_role_is_refused(client, signed):
    """Authenticated is not authorized: a directory account with no app role grants nothing."""
    token = signed(_claims(roles=[]))
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "ROLE_NOT_ASSIGNED"


def test_the_most_privileged_assigned_role_wins(client, signed):
    token = signed(_claims(roles=["VIEWER", "REVIEWER", "EDITOR"]))
    response = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 201


def test_a_role_claim_delivered_as_a_string_is_understood(client, signed):
    """Entra emits multi-valued claims as a list, a space-delimited string or a CSV string."""
    token = signed(_claims(roles="VIEWER EDITOR"))
    assert client.get("/api/v1/reports", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_a_token_carrying_no_product_scope_is_refused(client, signed):
    """Silence is not consent: an absent scope claim must not read as "every fund"."""
    claims = _claims()
    claims.pop("product_scope")
    response = client.get("/api/v1/reports", headers={"Authorization": f"Bearer {signed(claims)}"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "PRODUCT_SCOPE_NOT_ASSIGNED"


def test_scope_is_unrestricted_only_when_the_deployment_opts_out(client, signed, monkeypatch):
    monkeypatch.setattr(settings, "entra_product_scope_claim", "")
    claims = _claims()
    claims.pop("product_scope")
    assert client.get("/api/v1/reports", headers={"Authorization": f"Bearer {signed(claims)}"}).status_code == 200


def test_product_scope_from_the_token_filters_the_report_list(client, signed):
    admin = {"Authorization": f"Bearer {signed(_claims(roles=['ADMIN'], product_scope=['*']))}"}
    client.post("/api/v1/reports", json={"report_date": "2026-06-30", "product_code": "3033"}, headers=admin)
    client.post("/api/v1/reports", json={"report_date": "2026-06-30", "product_code": "3037"}, headers=admin)
    narrow = {"Authorization": f"Bearer {signed(_claims(product_scope=['3037']))}"}
    listed = client.get("/api/v1/reports", headers=narrow).json()
    assert {item["product_code"] for item in listed} == {"3037"}


def test_the_key_document_is_cached_between_requests(client, signed, monkeypatch):
    """Every request re-fetching the JWKS would put the identity provider on the hot path."""
    calls = {"count": 0}
    jwt = _crypto()

    def counted():
        calls["count"] += 1
        return _jwks(jwt)

    monkeypatch.setattr(entra, "_fetch_jwks", counted)
    entra.reset_key_cache()
    headers = {"Authorization": f"Bearer {signed()}"}
    for _ in range(3):
        assert client.get("/api/v1/reports", headers=headers).status_code == 200
    assert calls["count"] == 1


# --------------------------------------------------------------------------------------------
# Configuration that must not reach production
# --------------------------------------------------------------------------------------------


def _deployed(**overrides) -> Settings:
    base = {
        "auth_mode": "ENTRA",
        "download_secret": "x" * 48,
        "entra_audience": AUDIENCE,
        "entra_issuer": ISSUER,
        "entra_jwks_url": "https://login.microsoftonline.com/t/discovery/v2.0/keys",
        "entra_allowed_algorithms": ("RS256",),
        "allow_testing_lane": False,
        "database_url": "mysql+pymysql://user:pw@db/commentary?charset=utf8mb4",
    }
    return Settings(**{**base, **overrides})


def test_local_mode_is_exempt_from_the_deployment_guards():
    """LOCAL is the developer mode where the header is the identity and the key is public."""
    assert Settings(auth_mode="LOCAL", download_secret=DEFAULT_DOWNLOAD_SECRET).deployment_problems() == []


def test_a_correctly_configured_deployment_has_no_problems():
    assert _deployed().deployment_problems() == []


def test_the_repository_default_signing_secret_is_refused():
    problems = _deployed(download_secret=DEFAULT_DOWNLOAD_SECRET).deployment_problems()
    assert any("DOWNLOAD_SECRET" in problem for problem in problems)


def test_a_short_signing_secret_is_refused():
    problems = _deployed(download_secret="short").deployment_problems()
    assert any("32 characters" in problem for problem in problems)


def test_an_unknown_auth_mode_is_refused():
    """A typo in AUTH_MODE must not land somewhere between LOCAL and ENTRA."""
    problems = _deployed(auth_mode="ENTRAA").deployment_problems()
    assert any("AUTH_MODE" in problem for problem in problems)


@pytest.mark.parametrize("missing", ["entra_audience", "entra_issuer"])
def test_entra_without_audience_or_issuer_is_refused(missing):
    overrides = {missing: None}
    if missing == "entra_issuer":
        overrides["entra_tenant_id"] = None
    assert _deployed(**overrides).deployment_problems()


def test_symmetric_and_unsecured_algorithms_are_refused_in_configuration():
    assert any("HS" in problem for problem in _deployed(entra_allowed_algorithms=("RS256", "HS256")).deployment_problems())
    assert any("none" in problem for problem in _deployed(entra_allowed_algorithms=("RS256", "NONE")).deployment_problems())


def test_the_fixture_lane_must_be_shut_outside_local():
    """Transcribed golden data carries real-looking numbers that were never derived from a source."""
    problems = _deployed(allow_testing_lane=True).deployment_problems()
    assert any("ALLOW_TESTING_LANE" in problem for problem in problems)


def test_sqlite_is_refused_outside_local():
    problems = _deployed(database_url="sqlite:///var/commentary.db").deployment_problems()
    assert any("SQLite" in problem for problem in problems)


def test_the_application_refuses_to_start_on_an_unsafe_configuration(monkeypatch):
    """Discovering these in production means they were already used to serve traffic."""
    monkeypatch.setattr(settings, "auth_mode", "ENTRA")
    monkeypatch.setattr(settings, "download_secret", DEFAULT_DOWNLOAD_SECRET)
    with pytest.raises(ConfigurationError) as raised:
        create_app()
    assert "DOWNLOAD_SECRET" in str(raised.value)


def _run_container_entrypoint_guard(monkeypatch, **overrides):
    from pathlib import Path

    from app.core import config

    from app.core import deployment

    configured = {"task_mode": "EAGER", **overrides}
    monkeypatch.setattr(deployment, "settings", _deployed(**configured))
    deployment.verify_container_configuration()


def test_container_entrypoint_guard_accepts_production_configuration_without_network(monkeypatch):
    _run_container_entrypoint_guard(monkeypatch)


@pytest.mark.parametrize("mode", ["CELERY", "UNKNOWN", ""])
@pytest.mark.parametrize("auth_mode", ["LOCAL", "REMOTE"])
def test_removed_queue_modes_are_rejected_at_api_startup(monkeypatch, mode, auth_mode):
    monkeypatch.setattr(settings, "task_mode", mode)
    monkeypatch.setattr(settings, "auth_mode", auth_mode)
    with pytest.raises(ConfigurationError, match="TASK_MODE"):
        create_app()


@pytest.mark.parametrize("overrides", [
    {"auth_mode": "LOCAL"},
    {"database_url": "sqlite:///local.db"},
    {"database_url": "postgresql://user:password@db/app"},
    {"database_url": "mysql+pymysql://user:password@db/app?charset=utf8"},
    {"database_url": "not-a-url"},
    {"task_mode": "CELERY"},
    {"allow_testing_lane": True},
    {"download_secret": "short"},
])
def test_container_entrypoint_guard_refuses_unsafe_configuration_before_migration(monkeypatch, overrides):
    with pytest.raises(ConfigurationError):
        _run_container_entrypoint_guard(monkeypatch, **overrides)


def test_container_entrypoint_guard_redacts_malformed_database_url(monkeypatch):
    sensitive = "do-not-print-this-credential"
    with pytest.raises(ConfigurationError) as raised:
        _run_container_entrypoint_guard(monkeypatch, database_url=f"mysql+pymysql://user:{sensitive}@db:{sensitive}/app")
    assert sensitive not in str(raised.value)
    assert "DATABASE_URL" in str(raised.value)


def _k8s_secret_builder():
    from pathlib import Path
    import runpy

    path = Path(__file__).resolve().parents[2] / "k8s" / "create-secret.py"
    return runpy.run_path(str(path))["build_secret"]


def _k8s_secret_values(environment="uat"):
    values = {
        "DATABASE_URL": "mysql+pymysql://test:test@db.invalid/app?charset=utf8mb4",
        "DOWNLOAD_SECRET": "test-generated-placeholder-" * 3,
        "DA_REPORT_DATABASE_URL": "",
        "DA_REPORT_OBJECT_URL": "",
        "DA_REPORT_SQLITE_SHA256": "",
        "DATAWAREHOUSE_MYSQL_HOST": "",
        "DATAWAREHOUSE_MYSQL_DATABASE": "",
        "DATAWAREHOUSE_MYSQL_USERNAME": "",
        "DATAWAREHOUSE_MYSQL_PASSWORD": "literal$KEY with spaces=and-equals",
        "FMP_API_KEY": "",
        "TRANSLATION_API_KEY": "",
    }
    if environment == "prd":
        values.pop("DA_REPORT_OBJECT_URL")
        values.pop("DA_REPORT_SQLITE_SHA256")
        values["DA_REPORT_DATABASE_URL"] = "mysql+pymysql://readonly:test@da.invalid/da"
    return values


@pytest.mark.parametrize("environment", ["uat", "prd"])
def test_k8s_secret_builder_preserves_literal_values_and_all_optional_keys(tmp_path, environment):
    import base64

    values = _k8s_secret_values(environment)
    env_file = tmp_path / ".env.secrets"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    secret = _k8s_secret_builder()(environment, "ih", env_file)
    assert secret["metadata"]["name"] == f"ih-{environment}-remote-fund-cmt-auto-srvapp-secret"
    assert {key: base64.b64decode(value).decode("utf-8") for key, value in secret["data"].items()} == values
    assert "stringData" not in secret


def test_production_requires_its_da_database_while_uat_keeps_snapshot_configuration(tmp_path):
    values = _k8s_secret_values()
    values["DA_REPORT_OBJECT_URL"] = "https://objects.invalid/uat.sqlite"
    values["DA_REPORT_SQLITE_SHA256"] = "a" * 64
    path = tmp_path / ".env.test"
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    _k8s_secret_builder()("uat", "ih", path)
    values = _k8s_secret_values("prd")
    values["DA_REPORT_DATABASE_URL"] = ""
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    with pytest.raises(ValueError, match="DA_REPORT_DATABASE_URL"):
        _k8s_secret_builder()("prd", "ih", path)
    values["DA_REPORT_DATABASE_URL"] = "mysql+pymysql://readonly:test@da.invalid/da"
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    _k8s_secret_builder()("prd", "ih", path)


@pytest.mark.parametrize("retired_key", ["DA_REPORT_OBJECT_URL", "DA_REPORT_SQLITE_SHA256"])
def test_production_secret_refuses_retired_snapshot_keys(tmp_path, retired_key):
    values = _k8s_secret_values("prd")
    values[retired_key] = "do-not-print-retired-secret"
    path = tmp_path / ".env.prd"
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    with pytest.raises(ValueError) as raised:
        _k8s_secret_builder()("prd", "ih", path)
    assert "do-not-print-retired-secret" not in str(raised.value)


@pytest.mark.parametrize("environment", ["uat", "prd"])
@pytest.mark.parametrize("change", ["missing", "empty", "unexpected", "retired", "short", "namespace"])
def test_k8s_secret_builder_refuses_incomplete_or_unsafe_input_without_leaking_values(tmp_path, change, environment):
    values = _k8s_secret_values(environment)
    namespace = "ih"
    if change == "missing":
        values.pop("FMP_API_KEY")
    elif change == "empty":
        values["DATABASE_URL"] = ""
    elif change == "unexpected":
        values["AUTH_MODE"] = "LOCAL"
    elif change == "retired":
        values["MARKETAUX_API_KEY"] = "literal$KEY-retired-secret"
    elif change == "short":
        values["DOWNLOAD_SECRET"] = "short"
    else:
        namespace = "replace-me-namespace"
    env_file = tmp_path / ".env.secrets"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8")
    with pytest.raises(ValueError) as raised:
        _k8s_secret_builder()(environment, namespace, env_file)
    assert "literal$KEY" not in str(raised.value)



def test_remote_mode_needs_no_entra_but_still_enforces_deployment_guards():
    configured = _deployed(auth_mode="REMOTE", entra_audience=None, entra_issuer=None, entra_jwks_url=None, entra_tenant_id=None)
    assert configured.deployment_problems() == []
    for changes, expected in [
        ({"database_url": "sqlite:///local.db"}, "DATABASE_URL"),
        ({"download_secret": "short"}, "DOWNLOAD_SECRET"),
        ({"allow_testing_lane": True}, "ALLOW_TESTING_LANE"),
    ]:
        assert expected in " ".join(configured.model_copy(update=changes).deployment_problems())


def test_remote_mode_ignores_forged_actor_headers_and_does_not_require_token(client, monkeypatch):
    from starlette.datastructures import Headers
    from app.core.security import resolve_principal

    monkeypatch.setattr(settings, "auth_mode", "REMOTE")
    principal = resolve_principal(Headers({"X-User-ID": "forged-user", "X-User-Role": "VIEWER", "X-Product-Scope": "other"}))
    assert (principal.subject, principal.role, principal.product_scope) == ("remote-app", "ADMIN", frozenset({"*"}))
    response = client.get("/api/v1/reports", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 200


def test_remote_image_guard_accepts_no_entra_configuration(monkeypatch):
    _run_container_entrypoint_guard(monkeypatch, auth_mode="REMOTE", entra_audience=None,
                                    entra_tenant_id=None, entra_issuer=None, entra_jwks_url=None)


@pytest.mark.parametrize("key", ["DATABASE_URL", "DOWNLOAD_SECRET", "TRANSLATION_API_KEY"])
def test_secret_builder_rejects_duplicate_keys_without_leaking_values(tmp_path, key):
    values = _k8s_secret_values()
    path = tmp_path / ".env.uat"
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + f"\n{key}=do-not-print", encoding="utf-8")
    with pytest.raises(ValueError) as raised:
        _k8s_secret_builder()("uat", "ih", path)
    assert "do-not-print" not in str(raised.value)


def test_access_log_redacts_signed_queries_and_keeps_failed_probes():
    import logging
    from app.core.logging_setup import AccessLogFilter

    def record(path, status):
        return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                                 ("client", "GET", path, "1.1", status), None)
    filter_ = AccessLogFilter()
    assert filter_.filter(record("/api/v1/health", 200)) is False
    assert filter_.filter(record("/api/v1/health", 503)) is True
    signed = record("/api/v1/artifacts/file?signature=private-signature&subject=private-user", 200)
    assert filter_.filter(signed)
    assert "private" not in signed.getMessage()


def test_deep_health_redacts_failures_and_never_changes_shallow_probe(client, monkeypatch):
    from app.core import health

    def unavailable():
        raise RuntimeError("mysql://private:password@secret-host")
    monkeypatch.setattr(health, "database_check", unavailable)
    response = client.get("/api/v1/health/deep")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "dependencies": {"database": "unavailable"}}
    assert "private" not in response.text
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health/deep", headers={"X-User-Role": "VIEWER"}).status_code == 403
