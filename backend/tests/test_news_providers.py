"""DA-Report dispatch and the API boundary for unsupported news sources."""

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.integrations import news


@pytest.mark.parametrize("configured", [False, True])
def test_registry_exposes_only_da_report_and_its_availability(client, monkeypatch, configured):
    monkeypatch.setattr(settings, "news_provider", "DA_REPORT")
    monkeypatch.setattr("app.integrations.da_report.is_configured", lambda: configured)
    response = client.get("/api/v1/news/providers")
    assert response.status_code == 200, response.text
    providers = response.json()
    assert len(providers) == 1
    assert providers[0]["key"] == "DA_REPORT"
    assert providers[0]["configured"] is configured
    assert providers[0]["default"] is True
    assert set(providers[0]) == {"key", "title", "description", "configured", "default"}


@pytest.mark.parametrize("provider", [None, "DA_REPORT", "da_report"])
def test_report_fetch_keeps_da_dispatch_candidates_and_audit(client, monkeypatch, provider):
    async def fake_fetch(scope, symbols, from_date, to_date, page, limit, constituents=None):
        assert "0700.HK" in symbols
        assert constituents
        return [{
            "source_name": "example.test", "source_url": "https://example.test/da-news",
            "published_at": datetime(2026, 6, 12, 8, 30, tzinfo=timezone.utc), "title": "Approved company news",
            "summary": "Approved snippet", "ticker": "0700.HK",
            "metadata_json": {"provider": "DA_REPORT", "scope": scope, "site": "example.test", "dedupe_hash": "hash"},
        }]

    monkeypatch.setattr(settings, "news_provider", "DA_REPORT")
    monkeypatch.setattr("app.integrations.da_report.fetch_news", fake_fetch)
    report_response = client.post("/api/v1/reports", json={"report_date": "2026-06-30"})
    assert report_response.status_code == 201, report_response.text
    report_id = report_response.json()["id"]
    snapshot = client.post(f"/api/v1/reports/{report_id}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    assert snapshot.is_success, snapshot.text
    command = {"scope": "CONSTITUENTS"}
    if provider is not None:
        command["provider"] = provider
    fetched = client.post(f"/api/v1/reports/{report_id}/news/candidates/fetch", json=command)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["provider"] == "DA_REPORT"
    assert fetched.json()["created"] == 1
    candidate = client.get(f"/api/v1/reports/{report_id}/news/candidates").json()[0]
    assert candidate["provider"] == "DA_REPORT"
    assert candidate["security_code"] == "700"
    actions = [event["action"] for event in client.get(f"/api/v1/audit?report_id={report_id}").json()]
    assert "news.da_report_fetched" in actions


@pytest.mark.parametrize("provider", ["MARKETAUX", "marketaux", "NOT_A_VENDOR", None])
def test_unsupported_provider_is_rejected_without_fallback_or_fetch(client, monkeypatch, provider):
    async def unexpected_fetch(*args, **kwargs):
        pytest.fail("An unsupported provider must not fall back to DA-Report")

    monkeypatch.setattr("app.integrations.da_report.fetch_news", unexpected_fetch)
    # A stale default must fail just like an explicitly requested retired provider.
    monkeypatch.setattr(settings, "news_provider", "MARKETAUX" if provider is None else "DA_REPORT")
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    command = {"scope": "CONSTITUENTS"}
    if provider is not None:
        command["provider"] = provider
    response = client.post(f"/api/v1/reports/{report['id']}/news/candidates/fetch", json=command)
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "NEWS_PROVIDER_UNKNOWN"
    assert client.get(f"/api/v1/reports/{report['id']}/news/candidates").json() == []


def test_provider_key_selection_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(settings, "news_provider", "da_report")
    assert news.get_spec("da_report").key == "DA_REPORT"
    assert news.get_spec(None).key == "DA_REPORT"
