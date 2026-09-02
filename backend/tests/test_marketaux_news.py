"""Marketaux adapter and the provider registry the route now dispatches through.

Marketaux authenticates with an `api_token` query parameter and offers no header alternative, so the
credential unavoidably reaches the outbound URL. What these tests pin down is the part that is still
enforceable: the token never reaches a normalized candidate, an API response body, or an audit record.
"""

import asyncio
from datetime import date, datetime, timezone

import httpx
import pytest

from app.core.config import settings
from app.integrations import news
from app.integrations.marketaux import MarketauxProviderError, fetch_news

ARTICLE = {
    "uuid": "9f0d0d3e-0000-4000-8000-000000000001",
    "title": "Tencent lifts quarterly guidance",
    "description": "The company raised its outlook for the quarter.",
    "snippet": "…raised its outlook…",
    "url": "https://example.test/tencent-guidance",
    "image_url": "https://images.example.test/tencent.jpg",
    "language": "en",
    "published_at": "2026-06-12T08:30:00.000000Z",
    "source": "example.test",
    "entities": [
        {"symbol": "AAPL", "name": "Apple Inc", "type": "equity"},
        {"symbol": "0700.HK", "name": "Tencent Holdings", "type": "equity"},
    ],
}


def run(handler, scope="CONSTITUENTS", symbols=("0700.HK",), from_date=date(2026, 6, 1), to_date=date(2026, 6, 30)):
    async def call():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_news(scope, list(symbols), from_date, to_date, 0, 20, client)

    return asyncio.run(call())


def test_adapter_sends_the_token_as_a_query_parameter_and_keeps_it_out_of_the_output(monkeypatch):
    monkeypatch.setattr(settings, "marketaux_api_key", "marketaux-secret")
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["params"] = dict(request.url.params)
        return httpx.Response(200, json={"meta": {"found": 1}, "data": [ARTICLE]})

    items = run(handler)
    # Documented deviation from the header-only rule: Marketaux has no header auth.
    assert observed["params"]["api_token"] == "marketaux-secret"
    assert observed["params"]["symbols"] == "0700.HK"
    # Marketaux pages are 1-based while the shared interface is 0-based.
    assert observed["params"]["page"] == "1"
    assert observed["params"]["published_after"] == "2026-06-01T00:00:00"
    assert observed["params"]["published_before"] == "2026-06-30T23:59:59"
    assert items[0]["ticker"] == "0700.HK"
    assert items[0]["summary"] == "The company raised its outlook for the quarter."
    assert items[0]["metadata_json"]["provider"] == "MARKETAUX"
    assert "marketaux-secret" not in str(items)


def test_article_binds_to_the_requested_constituent_not_the_first_entity(monkeypatch):
    """Marketaux tags an article with every entity it mentions; the holding asked for must win."""
    monkeypatch.setattr(settings, "marketaux_api_key", "marketaux-secret")
    items = run(lambda request: httpx.Response(200, json={"data": [ARTICLE]}))
    assert items[0]["ticker"] == "0700.HK", "AAPL is listed first but is not a requested constituent"
    assert items[0]["metadata_json"]["matched_symbols"] == ["0700.HK"]


def test_articles_outside_the_requested_window_are_dropped(monkeypatch):
    monkeypatch.setattr(settings, "marketaux_api_key", "marketaux-secret")
    payload = {"data": [
        {**ARTICLE, "uuid": "a", "published_at": "2026-06-15T08:30:00.000000Z", "title": "Inside window", "url": "https://example.test/in"},
        {**ARTICLE, "uuid": "b", "published_at": "2026-07-02T08:30:00.000000Z", "title": "After window", "url": "https://example.test/after"},
        {**ARTICLE, "uuid": "c", "published_at": "2026-05-20T08:30:00.000000Z", "title": "Before window", "url": "https://example.test/before"},
    ]}
    items = run(lambda request: httpx.Response(200, json=payload))
    assert [item["title"] for item in items] == ["Inside window"]


def test_a_rejection_explains_itself_without_echoing_the_token(monkeypatch):
    """Marketaux error bodies can quote the request parameters back, api_token included."""
    monkeypatch.setattr(settings, "marketaux_api_key", "marketaux-secret")
    body = {"error": {"code": "invalid_api_token", "message": "api_token marketaux-secret is not valid"}}

    with pytest.raises(MarketauxProviderError) as raised:
        run(lambda request: httpx.Response(400, json=body))
    assert raised.value.code == "MARKETAUX_REQUEST_REJECTED"
    assert "invalid_api_token" in raised.value.message
    assert "marketaux-secret" not in raised.value.message
    assert "***" in raised.value.message


def test_quota_exhaustion_is_reported_as_not_retryable(monkeypatch):
    monkeypatch.setattr(settings, "marketaux_api_key", "marketaux-secret")
    with pytest.raises(MarketauxProviderError) as raised:
        run(lambda request: httpx.Response(402, json={}))
    assert (raised.value.code, raised.value.http_status, raised.value.retryable) == ("MARKETAUX_QUOTA_EXCEEDED", 503, False)


def test_fetch_fails_closed_when_the_secret_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "marketaux_api_key", None)
    with pytest.raises(MarketauxProviderError) as raised:
        run(lambda request: httpx.Response(200, json={"data": []}))
    assert raised.value.code == "MARKETAUX_NOT_CONFIGURED"


def test_registry_reports_which_providers_hold_a_credential(client, monkeypatch):
    monkeypatch.setattr(settings, "marketaux_api_key", "marketaux-secret")
    monkeypatch.setattr(settings, "da_report_sqlite_path", None)
    response = client.get("/api/v1/news/providers")
    assert response.status_code == 200, response.text
    by_key = {item["key"]: item for item in response.json()}
    assert set(by_key) == {"MARKETAUX", "DA_REPORT"}
    assert by_key["MARKETAUX"]["configured"] is True
    assert by_key["DA_REPORT"]["configured"] is False
    # Only the boolean is exposed; the credential itself never leaves the process.
    assert "marketaux-secret" not in response.text


def prepare(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    return report


def test_report_fetch_dispatches_to_the_named_provider(client, monkeypatch):
    async def fake_fetch(scope, symbols, from_date, to_date, page, limit):
        assert "0700.HK" in symbols
        return [{
            "source_name": "example.test", "source_url": "https://example.test/marketaux-news",
            "published_at": datetime(2026, 6, 12, 8, 30, tzinfo=timezone.utc), "title": "Marketaux sourced item",
            "summary": "Approved snippet", "ticker": "0700.HK",
            "metadata_json": {"provider": "MARKETAUX", "scope": scope, "site": "example.test", "dedupe_hash": "hash"},
        }]

    monkeypatch.setattr("app.integrations.marketaux.fetch_news", fake_fetch)
    report = prepare(client)
    fetched = client.post(f"/api/v1/reports/{report['id']}/news/candidates/fetch", json={"scope": "CONSTITUENTS", "provider": "MARKETAUX"})
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["provider"] == "MARKETAUX"
    assert fetched.json()["created"] == 1
    candidate = client.get(f"/api/v1/reports/{report['id']}/news/candidates").json()[0]
    assert candidate["provider"] == "MARKETAUX"
    assert candidate["security_code"] == "700"
    # Each provider gets its own audit action, so the trail says which vendor supplied the item.
    actions = [event["action"] for event in client.get(f"/api/v1/audit?report_id={report['id']}").json()]
    assert "news.marketaux_fetched" in actions


def test_omitting_the_provider_keeps_the_configured_default(client, monkeypatch):
    """Existing clients send no provider field and must keep reaching the configured default."""
    called = {}

    async def fake_fetch(scope, symbols, from_date, to_date, page, limit):
        called["provider"] = "MARKETAUX"
        return []

    monkeypatch.setattr("app.integrations.marketaux.fetch_news", fake_fetch)
    monkeypatch.setattr(settings, "news_provider", "MARKETAUX")
    report = prepare(client)
    response = client.post(f"/api/v1/reports/{report['id']}/news/candidates/fetch", json={"scope": "CONSTITUENTS"})
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "MARKETAUX"
    assert called["provider"] == "MARKETAUX"


def test_an_unknown_provider_is_rejected_before_any_call_is_made(client):
    report = prepare(client)
    response = client.post(f"/api/v1/reports/{report['id']}/news/candidates/fetch", json={"scope": "CONSTITUENTS", "provider": "NOT_A_VENDOR"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "NEWS_PROVIDER_UNKNOWN"


def test_provider_key_selection_is_case_insensitive():
    assert news.get_spec("marketaux").key == "MARKETAUX"
    assert news.get_spec(None).key == (settings.news_provider or "DA_REPORT").upper()
