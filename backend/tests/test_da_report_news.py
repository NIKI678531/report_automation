import asyncio
import hashlib
import sqlite3
from datetime import date
from pathlib import Path

from app.core.config import settings
import httpx
import pytest

from app.integrations.da_report import (
    DaReportProviderError,
    _company_aliases,
    _materialize_snapshot,
    _sqlite_contains_company_alias,
    fetch_news,
    list_company_news_catalog,
)
from app.integrations.datawarehouse import DataWarehouseProviderError
from app.domain.service import news as news_service


INGESTION_FIXTURE = Path(__file__).parent / "fixtures" / "ingestion" / "index_constituents.csv"


def build_da_snapshot(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE news_sources (
            id INTEGER PRIMARY KEY,
            code TEXT,
            name_en TEXT,
            name_zh TEXT,
            report_type TEXT
        );
        CREATE TABLE news_items (
            id INTEGER PRIMARY KEY,
            source_id INTEGER,
            url TEXT,
            title_raw TEXT,
            summary_raw TEXT,
            published_at TEXT,
            fetched_at TEXT
        );
        CREATE TABLE news_enrichments (
            news_item_id INTEGER,
            title_en TEXT,
            title_zh TEXT,
            summary_en TEXT,
            summary_zh TEXT,
            category TEXT,
            region TEXT,
            sentiment TEXT,
            importance_score REAL,
            model TEXT
        );
        INSERT INTO news_sources VALUES (1, 'source', 'Approved Source', '認可來源', 'regional');
        INSERT INTO news_sources VALUES (2, 'other', 'Other Source', '其他來源', 'da');
        INSERT INTO news_sources VALUES (3, 'archive', 'Archive Source', '歷史來源', 'regional');
        INSERT INTO news_items VALUES
            (1, 1, 'https://example.test/tencent', 'raw', 'raw', '2026-06-12 08:30:00', '2026-06-12 09:00:00'),
            (2, 1, 'https://example.test/tsmc', 'raw', 'raw', '2026-06-13 08:30:00', '2026-06-13 09:00:00'),
            (3, 1, 'https://example.test/general', 'raw', 'raw', '2026-06-14 08:30:00', '2026-06-14 09:00:00'),
            (4, 2, 'https://example.test/wrong-report', 'raw', 'raw', '2026-06-15 08:30:00', '2026-06-15 09:00:00'),
            (5, 1, 'https://example.test/outside', 'raw', 'raw', '2026-07-01 08:30:00', '2026-07-01 09:00:00'),
            (6, 3, 'https://example.test/no-published-at', 'raw', 'raw', NULL, '2026-05-01 09:00:00');
        INSERT INTO news_enrichments VALUES
            (1, 'Tencent raises its outlook', '騰訊控股上調展望', 'Tencent summary', '騰訊摘要', 'Corporate', 'China', 'bull', 88, 'test-model'),
            (2, 'Marvell adopts new chip process', 'Marvell 採用新製程', 'Taiwan Semiconductor Manufacturing expands capacity', '台積電擴產', 'Corporate', 'Taiwan', 'neutral', 80, 'test-model'),
            (3, 'Regional market update', '區域市場更新', 'No named holding', '未提及持倉', 'Market', 'China', 'neutral', 70, 'test-model'),
            (4, 'Tencent item in wrong report type', '其他報告的騰訊新聞', '', '', 'Corporate', 'China', 'neutral', 60, 'test-model'),
            (5, 'Tencent after report month', '報告月後的騰訊新聞', '', '', 'Corporate', 'China', 'neutral', 50, 'test-model'),
            (6, 'Tencent filing without publish time', '騰訊公告缺少發布時間', '', '', 'Corporate', 'China', 'bear', 72, 'test-model');
    """)
    connection.commit()
    connection.close()


def test_automatic_ensure_skips_a_pending_snapshot(client):
    report = client.post("/api/v1/reports", json={"product_code": "SLOT", "report_date": "2026-06-30"}).json()
    uploaded = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "index_constituents"},
        files={"file": (INGESTION_FIXTURE.name, INGESTION_FIXTURE.read_bytes(), "text/csv")},
    ).json()
    applied = client.post(f"/api/v1/reports/{report['id']}/imports/{uploaded['id']}/apply", json={})
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "PENDING"

    ensured = client.post(
        f"/api/v1/reports/{report['id']}/news/candidates/fetch",
        json={"scope": "CONSTITUENTS", "provider": "DA_REPORT", "ensure": True},
    )

    assert ensured.status_code == 200, ensured.text
    assert ensured.json()["skip_reason"] == "SNAPSHOT_NOT_VALID"


def test_da_report_returns_only_unique_title_matches_for_current_constituents(tmp_path, monkeypatch):
    database = tmp_path / "da report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    constituents = [
        {"security_code": "700", "ticker": "0700.HK", "name_en": "TENCENT", "name_zh_hant": "騰訊控股"},
        {"security_code": "981", "ticker": "0981.HK", "name_en": "SMIC", "name_zh_hant": "中芯國際"},
    ]

    items = asyncio.run(fetch_news(
        "CONSTITUENTS",
        ["0700.HK", "0981.HK"],
        date(2026, 6, 1),
        date(2026, 6, 30),
        0,
        20,
        constituents=constituents,
    ))

    assert [item["title"] for item in items] == ["Tencent raises its outlook"]
    assert items[0]["ticker"] == "0700.HK"
    assert items[0]["metadata_json"]["matched_security_code"] == "700"
    assert items[0]["metadata_json"]["match_method"] == "TITLE_ALIAS_EXACT"


def test_company_alias_matching_keeps_short_names_on_token_boundaries():
    assert _sqlite_contains_company_alias("NIO launches a new model", "NIO") == 1
    assert _sqlite_contains_company_alias("A senior executive comments", "NIO") == 0


def test_company_aliases_include_bilingual_names_controlled_aliases_and_full_ticker():
    aliases = _company_aliases({
        "ticker": "0700.HK",
        "name_en": "TENCENT",
        "name_zh_hant": "騰訊控股",
        "source_names": {"short_en": "Tencent", "short_zh": "騰訊"},
    })

    assert {"TENCENT", "騰訊控股", "腾讯控股", "騰訊", "0700 HK"}.issubset(aliases)
    assert _sqlite_contains_company_alias("腾讯发布季度业绩", "腾讯") == 1
    assert "騰訊控股" in _company_aliases({"name_zh_hans": "腾讯控股"})


@pytest.mark.parametrize(
    ("title", "alias"),
    [
        ("Tencent reports quarterly earnings", "TENCENT"),
        ("騰訊控股公布季度業績", "騰訊控股"),
        ("腾讯控股公布季度业绩", "腾讯控股"),
        ("騰訊公布季度業績", "騰訊"),
        ("0700.HK rises after quarterly earnings", "0700.HK"),
    ],
)
def test_company_title_alias_matching_supports_all_controlled_name_forms(title, alias):
    assert _sqlite_contains_company_alias(title, alias) == 1


def test_company_news_catalog_lists_all_regional_corporate_items_without_constituents(tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)

    page = asyncio.run(list_company_news_catalog(limit=20))

    assert [item["external_id"] for item in page["items"]] == ["5", "2", "1", "6"]
    assert [item["title"] for item in page["items"]] == [
        "Tencent after report month",
        "Marvell adopts new chip process",
        "Tencent raises its outlook",
        "Tencent filing without publish time",
    ]
    assert page["total"] == 4
    assert page["has_more"] is False
    assert page["facets"]["companies"] == []
    assert page["facets"]["sentiments"] == {"neutral": 2, "bear": 1, "bull": 1}
    assert page["items"][-1]["published_at_source"] == "fetched_at"


def test_company_news_catalog_uses_filter_bound_keyset_pagination(tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)

    first = asyncio.run(list_company_news_catalog(limit=2))
    second = asyncio.run(list_company_news_catalog(limit=2, cursor=first["next_cursor"]))
    oldest = asyncio.run(list_company_news_catalog(query="Tencent", sort="oldest", limit=20))

    assert [item["external_id"] for item in first["items"]] == ["5", "2"]
    assert [item["external_id"] for item in second["items"]] == ["1", "6"]
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert [item["external_id"] for item in oldest["items"]] == ["6", "1", "5"]
    with pytest.raises(DaReportProviderError) as raised:
        asyncio.run(list_company_news_catalog(query="Marvell", cursor=first["next_cursor"]))
    assert raised.value.code == "DA_REPORT_CURSOR_INVALID"
    with pytest.raises(DaReportProviderError) as malformed:
        asyncio.run(list_company_news_catalog(cursor="not-a-valid-cursor"))
    assert malformed.value.code == "DA_REPORT_CURSOR_INVALID"


def test_company_news_catalog_combines_source_sentiment_importance_and_date_filters(tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)

    page = asyncio.run(list_company_news_catalog(
        source="archive",
        sentiment="bear",
        importance="HIGH",
        from_date=date(2026, 5, 1),
        to_date=date(2026, 5, 1),
    ))

    assert [item["external_id"] for item in page["items"]] == ["6"]
    assert page["items"][0]["published_at_source"] == "fetched_at"
    assert page["total"] == 1


def test_company_news_catalog_filters_by_constituent_title_alias_and_composes_with_facets(tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    constituents = [
        {"security_code": "700", "ticker": "0700.HK", "name_en": "TENCENT", "name_zh_hans": None, "name_zh_hant": "騰訊控股"},
        {"security_code": "981", "ticker": "0981.HK", "name_en": "SMIC", "name_zh_hans": None, "name_zh_hant": "中芯國際"},
    ]

    page = asyncio.run(list_company_news_catalog(
        company="700",
        constituents=constituents,
        source="archive",
        sentiment="bear",
        importance="HIGH",
        limit=20,
    ))

    assert [item["external_id"] for item in page["items"]] == ["6"]
    assert page["total"] == 1
    assert page["facets"]["companies"] == [
        {"security_code": "700", "ticker": "0700.HK", "name_en": "TENCENT", "name_zh_hans": "腾讯控股", "name_zh_hant": "騰訊控股"},
        {"security_code": "981", "ticker": "0981.HK", "name_en": "SMIC", "name_zh_hans": "中芯国际", "name_zh_hant": "中芯國際"},
    ]

    first = asyncio.run(list_company_news_catalog(company="700", constituents=constituents, limit=2))
    assert first["next_cursor"]
    with pytest.raises(DaReportProviderError) as mismatched_cursor:
        asyncio.run(list_company_news_catalog(
            company="981",
            constituents=constituents,
            cursor=first["next_cursor"],
        ))
    assert mismatched_cursor.value.code == "DA_REPORT_CURSOR_INVALID"

    with pytest.raises(DaReportProviderError) as raised:
        asyncio.run(list_company_news_catalog(company="999999", constituents=constituents))
    assert raised.value.code == "DA_REPORT_COMPANY_INVALID"


def test_company_news_catalog_excludes_summary_only_company_matches(tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)

    page = asyncio.run(list_company_news_catalog(
        company="2330",
        constituents=[{
            "security_code": "2330",
            "ticker": "2330.TW",
            "name_en": "Taiwan Semiconductor Manufacturing",
            "name_zh_hant": "台積電",
        }],
        limit=20,
    ))

    assert page["items"] == []
    assert page["total"] == 0


def test_company_news_catalog_filters_to_any_constituent_title_and_binds_cursor(tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    constituents = [
        {"security_code": "700", "ticker": "0700.HK", "name_en": "TENCENT", "name_zh_hant": "騰訊控股"},
        {"security_code": "MRVL", "ticker": "MRVL.US", "name_en": "MARVELL", "name_zh_hant": "邁威爾科技"},
        {"security_code": "2330", "ticker": "2330.TW", "name_en": "Taiwan Semiconductor Manufacturing", "name_zh_hant": "台積電"},
    ]

    page = asyncio.run(list_company_news_catalog(
        company_scope="CONSTITUENTS",
        constituents=constituents,
        limit=20,
    ))

    assert [item["external_id"] for item in page["items"]] == ["5", "2", "1", "6"]
    assert page["total"] == 4

    first = asyncio.run(list_company_news_catalog(
        company_scope="CONSTITUENTS",
        constituents=constituents,
        limit=2,
    ))
    with pytest.raises(DaReportProviderError) as mismatched_cursor:
        asyncio.run(list_company_news_catalog(
            constituents=constituents,
            cursor=first["next_cursor"],
            limit=2,
        ))
    assert mismatched_cursor.value.code == "DA_REPORT_CURSOR_INVALID"


def test_company_news_catalog_rejects_unavailable_or_conflicting_constituent_scope(tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)

    with pytest.raises(DaReportProviderError) as unavailable:
        asyncio.run(list_company_news_catalog(company_scope="CONSTITUENTS"))
    assert unavailable.value.code == "DA_REPORT_CONSTITUENTS_UNAVAILABLE"

    with pytest.raises(DaReportProviderError) as conflict:
        asyncio.run(list_company_news_catalog(
            company="700",
            company_scope="CONSTITUENTS",
            constituents=[{"security_code": "700", "name_en": "TENCENT"}],
        ))
    assert conflict.value.code == "DA_REPORT_COMPANY_FILTER_CONFLICT"


def test_report_company_news_catalog_does_not_require_an_active_snapshot(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    monkeypatch.setattr(
        news_service,
        "load_report_month_index_constituents",
        lambda **kwargs: (_ for _ in ()).throw(
            DataWarehouseProviderError("DATAWAREHOUSE_UNAVAILABLE", "not available")
        ),
    )
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()

    first = client.get(f"/api/v1/reports/{report['id']}/news/catalog?limit=2")

    assert first.status_code == 200, first.text
    assert [item["external_id"] for item in first.json()["items"]] == ["5", "2"]
    assert first.json()["facets"]["companies"] == []
    assert first.json()["facets"]["date_min"] == "2026-05-01"
    cursor = first.json()["next_cursor"]
    second = client.get(
        f"/api/v1/reports/{report['id']}/news/catalog",
        params={"limit": 2, "cursor": cursor},
    )
    assert second.status_code == 200, second.text
    assert [item["external_id"] for item in second.json()["items"]] == ["1", "6"]


def test_report_company_news_catalog_uses_report_month_cdb_without_a_snapshot(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    constituents = [{
        "security_code": "700",
        "ticker": "0700.HK",
        "name_en": "TENCENT",
        "name_zh_hant": "騰訊控股",
    }, *[{
        "security_code": str(1000 + index),
        "ticker": f"{1000 + index:04d}.HK",
        "name_en": f"COMPANY {index}",
        "name_zh_hant": f"公司{index}",
    } for index in range(1, 30)]]
    monkeypatch.setattr(
        news_service,
        "load_report_month_index_constituents",
        lambda **kwargs: {"constituents": constituents, "effective_as_of": "2026-06-29"},
    )
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()

    response = client.get(
        f"/api/v1/reports/{report['id']}/news/catalog",
        params={"company": "700", "limit": 20},
    )

    assert response.status_code == 200, response.text
    assert [item["external_id"] for item in response.json()["items"]] == ["5", "1", "6"]
    assert len(response.json()["facets"]["companies"]) == 30
    assert response.json()["facets"]["companies"][0]["name_zh_hans"] == "腾讯控股"


def test_report_company_news_catalog_ignores_incomplete_cdb_company_list(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    monkeypatch.setattr(
        news_service,
        "load_report_month_index_constituents",
        lambda **kwargs: {"constituents": [{"security_code": "700", "name_en": "TENCENT"}]},
    )
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()

    response = client.get(f"/api/v1/reports/{report['id']}/news/catalog?limit=20")

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 4
    assert response.json()["facets"]["companies"] == []
    scoped = client.get(
        f"/api/v1/reports/{report['id']}/news/catalog",
        params={"company_scope": "CONSTITUENTS"},
    )
    assert scoped.status_code == 422
    assert scoped.json()["error_code"] == "DA_REPORT_CONSTITUENTS_UNAVAILABLE"


def test_report_company_news_catalog_exposes_and_filters_current_constituents(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    snapshot = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE"},
    )
    assert snapshot.status_code == 201, snapshot.text

    filtered = client.get(
        f"/api/v1/reports/{report['id']}/news/catalog",
        params={"company": "700", "limit": 20},
    )

    assert filtered.status_code == 200, filtered.text
    assert [item["external_id"] for item in filtered.json()["items"]] == ["5", "1", "6"]
    companies = filtered.json()["facets"]["companies"]
    assert len(companies) == 30
    assert next(item for item in companies if item["security_code"] == "700") == {
        "security_code": "700",
        "ticker": "0700.HK",
        "name_en": "TENCENT",
        "name_zh_hans": "腾讯控股",
        "name_zh_hant": "騰訊控股",
    }

    invalid = client.get(
        f"/api/v1/reports/{report['id']}/news/catalog",
        params={"company": "NOT-A-CONSTITUENT"},
    )
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["error_code"] == "DA_REPORT_COMPANY_INVALID"

    conflict = client.get(
        f"/api/v1/reports/{report['id']}/news/catalog",
        params={"company": "700", "company_scope": "CONSTITUENTS"},
    )
    assert conflict.status_code == 422, conflict.text
    assert conflict.json()["error_code"] == "DA_REPORT_COMPANY_FILTER_CONFLICT"


def test_da_catalog_selection_materializes_lineage_and_warns_after_report_date(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    detail = client.get(f"/api/v1/reports/{report['id']}").json()

    selected = client.put(f"/api/v1/reports/{report['id']}/news", json={
        "version": detail["latest_document"]["version"],
        "items": [{"provider": "DA_REPORT", "external_id": "5", "position": 0}],
    })

    assert selected.status_code == 200, selected.text
    item = selected.json()["items"][0]
    assert item["title"] == "Tencent after report month"
    assert item["provider"] == "DA_REPORT"
    assert item["external_id"] == "5"
    assert item["sentiment"] == "neutral"
    stored = client.get(f"/api/v1/reports/{report['id']}").json()["latest_document"]["content"]
    assert stored["sections"]["company_news"][0]["news_item_id"]
    review = client.get(f"/api/v1/reports/{report['id']}/review").json()
    warning = next(item for item in review["checks"] if item["check_id"] == "NEWS_AFTER_REPORT_DATE")
    assert warning["severity"] == "WARNING"
    assert warning["status"] == "WARNING"


def test_report_fetch_dispatches_da_report_with_active_constituents(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    snapshot = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE"},
    )
    assert snapshot.status_code == 201, snapshot.text

    fetched = client.post(
        f"/api/v1/reports/{report['id']}/news/candidates/fetch",
        json={"scope": "CONSTITUENTS", "provider": "DA_REPORT", "ensure": True},
    )

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["provider"] == "DA_REPORT"
    assert fetched.json()["created"] == 1, fetched.text
    assert fetched.json()["items"][0]["security_code"] == "700"
    assert fetched.json()["items"][0]["importance"] == "HIGH"
    candidates = client.get(f"/api/v1/reports/{report['id']}/news/candidates").json()
    assert [item["title"] for item in candidates] == ["Tencent raises its outlook"]
    actions = [
        event["action"]
        for event in client.get(f"/api/v1/audit?report_id={report['id']}").json()
    ]
    assert "news.da_report_fetched" in actions
    repeated = client.post(
        f"/api/v1/reports/{report['id']}/news/candidates/fetch",
        json={"scope": "CONSTITUENTS", "provider": "DA_REPORT", "ensure": True},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["skip_reason"] == "CANDIDATES_ALREADY_EXIST"
    assert repeated.json()["fetched"] == 0


def test_draft_lists_candidates_from_same_product_and_report_month(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    data_ready = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    snapshot = client.post(
        f"/api/v1/reports/{data_ready['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE"},
    )
    assert snapshot.status_code == 201, snapshot.text
    fetched = client.post(
        f"/api/v1/reports/{data_ready['id']}/news/candidates/fetch",
        json={"scope": "CONSTITUENTS", "provider": "DA_REPORT", "ensure": True},
    )
    assert fetched.status_code == 200, fetched.text
    draft = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()

    candidates = client.get(f"/api/v1/reports/{draft['id']}/news/candidates")

    assert candidates.status_code == 200, candidates.text
    assert [item["title"] for item in candidates.json()] == ["Tencent raises its outlook"]


def test_draft_ensures_candidates_with_same_context_valid_snapshot(client, tmp_path, monkeypatch):
    database = tmp_path / "da-report.sqlite"
    build_da_snapshot(database)
    monkeypatch.setattr(settings, "da_report_sqlite_path", database)
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", None)
    data_ready = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    snapshot = client.post(
        f"/api/v1/reports/{data_ready['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE"},
    )
    assert snapshot.status_code == 201, snapshot.text
    draft = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()

    fetched = client.post(
        f"/api/v1/reports/{draft['id']}/news/candidates/fetch",
        json={"scope": "CONSTITUENTS", "provider": "DA_REPORT", "ensure": True},
    )

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["created"] == 1, fetched.text
    assert fetched.json()["items"][0]["title"] == "Tencent raises its outlook"
    unchanged = client.get(f"/api/v1/reports/{draft['id']}").json()
    assert unchanged["status"] == "DRAFT"
    assert unchanged["active_snapshot_id"] is None


def test_draft_auto_ensure_without_context_is_quiet_but_manual_fetch_is_blocked(client):
    draft = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()

    ensured = client.post(
        f"/api/v1/reports/{draft['id']}/news/candidates/fetch",
        json={"scope": "CONSTITUENTS", "provider": "DA_REPORT", "ensure": True},
    )
    manual = client.post(
        f"/api/v1/reports/{draft['id']}/news/candidates/fetch",
        json={"scope": "CONSTITUENTS", "provider": "DA_REPORT"},
    )

    assert ensured.status_code == 200, ensured.text
    assert ensured.json()["skip_reason"] == "CONSTITUENT_SNAPSHOT_UNAVAILABLE"
    assert ensured.json()["items"] == []
    assert manual.status_code == 422, manual.text
    assert manual.json()["error_code"] == "SNAPSHOT_REQUIRED"


def test_object_snapshot_is_downloaded_atomically_to_ephemeral_cache(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite"
    build_da_snapshot(source)
    content = source.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(settings, "da_report_sqlite_path", None)
    monkeypatch.setattr(settings, "da_report_object_url", "https://objects.example.test/da-report.sqlite?signature=secret")
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", checksum)
    monkeypatch.setattr(settings, "da_report_cache_dir", tmp_path / "ephemeral")
    monkeypatch.setattr(settings, "da_report_max_bytes", len(content) + 1)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content)))

    materialized = _materialize_snapshot(client)

    assert materialized.parent == tmp_path / "ephemeral"
    assert materialized.read_bytes() == content
    assert not list(materialized.parent.glob("*.part"))
    client.close()


def test_object_snapshot_checksum_failure_does_not_publish_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "da_report_sqlite_path", None)
    monkeypatch.setattr(settings, "da_report_object_url", "https://objects.example.test/da-report.sqlite?signature=secret")
    monkeypatch.setattr(settings, "da_report_sqlite_sha256", "0" * 64)
    monkeypatch.setattr(settings, "da_report_cache_dir", tmp_path / "ephemeral")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"not-the-approved-object")))

    with pytest.raises(DaReportProviderError) as raised:
        _materialize_snapshot(client)

    assert raised.value.code == "DA_REPORT_CHECKSUM_MISMATCH"
    assert not list((tmp_path / "ephemeral").glob("*"))
    assert "signature=secret" not in raised.value.message
    client.close()
