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
    body = response.json()
    assert {key: body[key] for key in ("error_code", "message", "retryable")} == {
        "error_code": "FMP_NOT_CONFIGURED",
        "message": "FMP news is not configured for this environment.",
        "retryable": False,
    }
    assert client.get(f"/api/v1/reports/{report['id']}/news/candidates").status_code == 200


def test_general_scope_drops_articles_outside_the_requested_window(monkeypatch):
    """news/general-latest ignores from/to, so the adapter must enforce the window itself."""
    monkeypatch.setattr(settings, "fmp_api_key", "test-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[
            {"symbol": None, "publishedDate": "2026-06-15 08:30:00", "publisher": "P", "title": "Inside window",
             "site": "example.test", "text": "", "url": "https://example.test/inside"},
            {"symbol": None, "publishedDate": "2026-07-02 08:30:00", "publisher": "P", "title": "After window",
             "site": "example.test", "text": "", "url": "https://example.test/after"},
            {"symbol": None, "publishedDate": "2026-05-20 08:30:00", "publisher": "P", "title": "Before window",
             "site": "example.test", "text": "", "url": "https://example.test/before"},
        ])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_news("GENERAL", [], date(2026, 6, 1), date(2026, 6, 30), 0, 20, client)

    assert [item["title"] for item in asyncio.run(run())] == ["Inside window"]


def test_candidates_expose_provider_site_for_filtering(client, monkeypatch):
    async def fake_fetch(scope, symbols, from_date, to_date, page, limit):
        return [{
            "source_name": "Approved Publisher", "source_url": "https://example.test/site-news",
            "published_at": datetime(2026, 6, 12, 8, 30, tzinfo=timezone.utc), "title": "Sited news",
            "summary": "Approved snippet", "ticker": "0700.HK",
            "metadata_json": {"provider": "FMP", "scope": scope, "site": "example.test", "dedupe_hash": "hash"},
        }]

    monkeypatch.setattr("app.integrations.fmp.fetch_news", fake_fetch)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    client.post(f"/api/v1/reports/{report['id']}/news/candidates/fetch", json={"scope": "CONSTITUENTS"})
    candidate = client.get(f"/api/v1/reports/{report['id']}/news/candidates").json()[0]
    assert candidate["site"] == "example.test"
    assert candidate["provider"] == "FMP"


def test_manual_candidate_is_scoped_to_the_report_and_marked_manual(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
    created = client.post(f"/api/v1/reports/{report['id']}/news/candidates", json={
        "source_name": "Desk note", "source_url": "https://desk.example.test/tencent",
        "published_at": "2026-06-12T08:30:00+00:00", "title": "Manually added item",
        "summary": "Analyst supplied summary", "ticker": "0700.HK",
    })
    assert created.status_code == 201, created.text
    assert created.json()["provider"] == "MANUAL"
    assert created.json()["site"] == "desk.example.test"
    # Constituent matching runs for manual entries too, so the item binds to the snapshot security.
    assert created.json()["security_code"] == "700"
    listed = client.get(f"/api/v1/reports/{report['id']}/news/candidates").json()
    assert [item["title"] for item in listed] == ["Manually added item"]


def test_manual_candidate_cannot_be_published_after_the_report_date(client):
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    response = client.post(f"/api/v1/reports/{report['id']}/news/candidates", json={
        "source_name": "Desk note", "source_url": "https://desk.example.test/late",
        "published_at": "2026-07-05T08:30:00+00:00", "title": "Too late",
        "summary": "", "ticker": None,
    })
    assert response.status_code == 422
    assert response.json()["error_code"] == "NEWS_DATE_RANGE_INVALID"


def test_same_article_can_be_related_to_two_reports_without_duplicate_news_rows(client, monkeypatch):
    async def fake_fetch(scope, symbols, from_date, to_date, page, limit):
        return [{
            "source_name": "Approved Publisher",
            "source_url": "https://example.test/shared-article",
            "published_at": datetime(2026, 6, 12, 8, 30, tzinfo=timezone.utc),
            "title": "Tencent shared report news",
            "summary": "Approved snippet",
            "ticker": "0700.HK",
            "metadata_json": {"provider": "FMP", "scope": scope, "dedupe_hash": "shared"},
        }]

    monkeypatch.setattr("app.integrations.fmp.fetch_news", fake_fetch)
    reports = []
    for _ in range(2):
        report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
        client.post(f"/api/v1/reports/{report['id']}/snapshots", json={"source_policy": "GOLDEN_FIXTURE"})
        fetched = client.post(f"/api/v1/reports/{report['id']}/news/candidates/fetch", json={"scope": "CONSTITUENTS"})
        assert fetched.status_code == 200, fetched.text
        reports.append(report)

    first = client.get(f"/api/v1/reports/{reports[0]['id']}/news/candidates").json()
    second = client.get(f"/api/v1/reports/{reports[1]['id']}/news/candidates").json()
    assert len(first) == len(second) == 1
    assert first[0]["id"] == second[0]["id"]