import asyncio
from datetime import date, datetime, timezone

import httpx

from app.core.config import settings
from app.integrations.fmp import fetch_news


def test_fmp_adapter_uses_header_auth_and_normalizes_without_leaking_key(monkeypatch):
    monkeypatch.setattr(settings, "fmp_api_key", "test-secret")
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["apikey"] = request.headers.get("apikey")
        return httpx.Response(200, json=[{
            "symbol": "0700.HK", "publishedDate": "2026-06-12 08:30:00", "publisher": "Approved Publisher",
            "title": "Tencent update", "image": "https://images.example.test/tencent.jpg", "site": "example.test",
            "text": "Approved snippet", "url": "https://example.test/tencent-update",
        }])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_news("CONSTITUENTS", ["0700.HK"], date(2026, 6, 1), date(2026, 6, 30), 0, 20, client)

    items = asyncio.run(run())
    assert observed["apikey"] == "test-secret"
    assert "test-secret" not in observed["url"]
    assert items[0]["ticker"] == "0700.HK"
    assert items[0]["summary"] == "Approved snippet"
    assert "test-secret" not in str(items)


def test_report_fmp_candidates_are_scoped_and_match_constituents(client, monkeypatch):
    async def fake_fetch(scope, symbols, from_date, to_date, page, limit):
        assert scope == "CONSTITUENTS"
        assert "0700.HK" in symbols
        return [{
            "source_name": "Approved Publisher", "source_url": "https://example.test/report-news",
            "published_at": datetime(2026, 6, 12, 8, 30, tzinfo=timezone.utc), "title": "Tencent report news",
            "summary": "Approved snippet", "ticker": "0700.HK",
            "metadata_json": {"provider": "FMP", "scope": scope, "dedupe_hash": "hash", "fetched_at": "2026-06-12T08:31:00+00:00"},
        }]

    monkeypatch.setattr("app.integrations.fmp.fetch_news", fake_fetch)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    fetched = client.post(f"/api/v1/reports/{report['id']}/news/candidates/fetch", json={"scope": "CONSTITUENTS"})
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["created"] == 1
    assert fetched.json()["items"][0]["security_code"] == "700"
    candidates = client.get(f"/api/v1/reports/{report['id']}/news/candidates")
    assert candidates.status_code == 200
    assert [item["title"] for item in candidates.json()] == ["Tencent report news"]


def test_fmp_fetch_fails_closed_when_secret_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "fmp_api_key", None)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    response = client.post(f"/api/v1/reports/{report['id']}/news/candidates/fetch", json={"scope": "CONSTITUENTS"})
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error_code": "FMP_NOT_CONFIGURED",
        "message": "FMP news is not configured for this environment.",
        "retryable": False,
    }
    assert client.get(f"/api/v1/reports/{report['id']}/news/candidates").status_code == 200