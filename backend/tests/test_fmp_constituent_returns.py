from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.domain.service.snapshots import (
    enrich_constituent_returns,
    has_approved_constituent_bundle,
)
from app.integrations.fmp import FmpProviderError, fmp_symbol, load_constituent_returns


def test_fmp_loads_selected_month_total_returns_with_auditable_observations(monkeypatch):
    monkeypatch.setattr(settings, "fmp_constituent_returns_enabled", True)
    monkeypatch.setattr(settings, "fmp_api_key", "test-secret")
    monkeypatch.setattr(settings, "fmp_base_url", "https://financialmodelingprep.com/stable")
    monkeypatch.setattr(settings, "fmp_allowed_hosts", ("financialmodelingprep.com",))
    prices = {
        "0700.HK": [
            ("2026-06-30", 132), ("2026-05-29", 120),
            ("2026-03-31", 110), ("2025-12-31", 100),
        ],
        "2513.HK": [
            ("2026-06-30", 60), ("2026-05-29", 55), ("2026-03-31", 50),
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/stable/historical-price-eod/dividend-adjusted"
        assert request.headers["apikey"] == "test-secret"
        assert "apikey" not in request.url.params
        symbol = request.url.params["symbol"]
        return httpx.Response(200, json=[
            {"symbol": symbol, "date": day, "adjClose": value}
            for day, value in prices[symbol]
        ])

    constituents = [
        {"security_code": "700", "ticker": "0700.HK", "name_en": "TENCENT"},
        {"security_code": "2513", "ticker": "2513.HK", "name_en": "KNOWLEDGE ATLAS"},
    ]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = load_constituent_returns(constituents, date(2026, 6, 30), client)

    assert result["return_periods"] == {
        "starts": {
            "return_1m": "2026-05-29",
            "return_3m": "2026-03-31",
            "return_6m": "2025-12-31",
            "return_ytd": "2025-12-31",
        },
        "end": "2026-06-30",
        "source": "Financial Modeling Prep dividend-adjusted EOD",
    }
    by_code = {row["security_code"]: row for row in result["constituent_returns"]}
    assert Decimal(by_code["700"]["return_1m"]) == Decimal("0.1")
    assert Decimal(by_code["700"]["return_3m"]) == Decimal("0.2")
    assert Decimal(by_code["700"]["return_6m"]) == Decimal("0.32")
    assert by_code["2513"]["return_6m"] is None
    assert by_code["2513"]["return_6m_missing_reason"] == "INSUFFICIENT_HISTORY"
    lineage = result["datasets"]["constituent_returns"]["lineage"]
    assert lineage["price_field"] == "adjClose"
    assert lineage["observations"][0]["resolved_symbol"] == "0700.HK"
    assert result["_findings"][0]["check_id"] == "FMP_CONSTITUENT_RETURN_COVERAGE"


def test_fmp_symbol_uses_hong_kong_security_code_when_ticker_is_not_usable():
    assert fmp_symbol({"security_code": "700", "ticker": "700 HK Equity"}) == "0700.HK"
    assert fmp_symbol({"security_code": "100", "name_en": "MINIMAX"}) == "0100.HK"


def test_fmp_requires_a_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "fmp_constituent_returns_enabled", True)
    monkeypatch.setattr(settings, "fmp_api_key", None)
    with pytest.raises(FmpProviderError) as error:
        load_constituent_returns([{"security_code": "700"}], date(2026, 6, 30))
    assert error.value.code == "FMP_NOT_CONFIGURED"


def test_fmp_enrichment_does_not_replace_uploaded_returns(monkeypatch):
    monkeypatch.setattr(settings, "fmp_constituent_returns_enabled", True)
    payload = {
        "constituents": [{"security_code": "700", "return_1m": "0.1"}],
        "datasets": {
            "index_constituents": {"source_type": "UPLOAD"},
            "constituent_returns": {"source_type": "UPLOAD"},
        },
    }
    assert enrich_constituent_returns(payload, date(2026, 6, 30)) == []
    assert payload["constituents"][0]["return_1m"] == "0.1"


def test_fmp_enrichment_fills_legacy_canonical_upload_when_all_returns_are_missing(monkeypatch):
    monkeypatch.setattr(settings, "fmp_constituent_returns_enabled", True)
    payload = {
        "constituents": [{
            "security_code": "700",
            "ticker": "0700.HK",
            "name_en": "TENCENT",
            "weight": "0.08",
            "return_1m": None,
            "return_1m_missing_reason": "PENDING_AUTOMATIC_SOURCE",
            "return_3m": None,
            "return_3m_missing_reason": "PENDING_AUTOMATIC_SOURCE",
            "return_6m": None,
            "return_6m_missing_reason": "PENDING_AUTOMATIC_SOURCE",
            "return_ytd": None,
            "return_ytd_missing_reason": "PENDING_AUTOMATIC_SOURCE",
        }],
        "datasets": {"constituent_performance": {"source_type": "UPLOAD"}},
    }
    fragment = {
        "constituent_returns": [{
            "security_code": "700",
            "return_1m": "0.1",
            "return_3m": "0.2",
            "return_6m": "0.3",
            "return_ytd": "0.4",
        }],
        "return_periods": {"starts": {}, "end": "2026-06-30", "source": "FMP"},
        "datasets": {"constituent_returns": {"source_type": "FMP_API"}},
        "_findings": [],
    }
    monkeypatch.setattr("app.domain.service.snapshots.load_constituent_returns", lambda *_: fragment)

    assert enrich_constituent_returns(payload, date(2026, 6, 30)) == []
    assert payload["constituents"][0]["return_ytd"] == "0.4"
    assert "return_ytd_missing_reason" not in payload["constituents"][0]
    assert payload["datasets"]["constituent_performance"]["source_type"] == "UPLOAD"
    assert payload["datasets"]["constituent_returns"]["source_type"] == "FMP_API"


def test_fmp_enrichment_preserves_numeric_returns_from_legacy_canonical_upload(monkeypatch):
    monkeypatch.setattr(settings, "fmp_constituent_returns_enabled", True)
    payload = {
        "constituents": [{"security_code": "700", "return_1m": "0.1"}],
        "datasets": {"constituent_performance": {"source_type": "UPLOAD"}},
    }
    called = False

    def unexpected_call(*_):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr("app.domain.service.snapshots.load_constituent_returns", unexpected_call)

    assert enrich_constituent_returns(payload, date(2026, 6, 30)) == []
    assert not called
    assert payload["constituents"][0]["return_1m"] == "0.1"


def test_fmp_enrichment_merges_returns_without_replacing_identity(monkeypatch):
    monkeypatch.setattr(settings, "fmp_constituent_returns_enabled", True)
    payload = {
        "constituents": [{
            "security_code": "700",
            "ticker": "0700.HK",
            "name_en": "TENCENT",
            "weight": "0.08",
        }],
        "datasets": {"index_constituents": {"source_type": "UPLOAD"}},
    }
    fragment = {
        "constituent_returns": [{
            "security_code": "700",
            "return_1m": "0.1",
            "return_3m": "0.2",
            "return_6m": "0.3",
            "return_ytd": "0.4",
        }],
        "return_periods": {
            "starts": {
                "return_1m": "2026-05-29",
                "return_3m": "2026-03-31",
                "return_6m": "2025-12-31",
                "return_ytd": "2025-12-31",
            },
            "end": "2026-06-30",
            "source": "Financial Modeling Prep dividend-adjusted EOD",
        },
        "datasets": {"constituent_returns": {"source_type": "FMP_API"}},
        "_findings": [],
    }
    monkeypatch.setattr("app.domain.service.snapshots.load_constituent_returns", lambda *_: fragment)

    assert enrich_constituent_returns(payload, date(2026, 6, 30)) == []
    assert payload["constituents"][0]["weight"] == "0.08"
    assert payload["constituents"][0]["return_ytd"] == "0.4"
    assert payload["return_periods"]["end"] == "2026-06-30"
    assert payload["datasets"]["constituent_returns"]["source_type"] == "FMP_API"


def test_production_bundle_accepts_uploaded_identity_with_fmp_returns():
    payload = {
        "constituents": [{
            "security_code": "700",
            "return_1m": "0.1",
            "return_3m": "0.2",
            "return_6m": "0.3",
            "return_ytd": "0.4",
        }],
        "datasets": {
            "index_constituents": {"source_type": "UPLOAD"},
            "constituent_returns": {"source_type": "FMP_API"},
        },
    }
    assert has_approved_constituent_bundle(payload)


def test_production_bundle_rejects_incomplete_period_coverage():
    payload = {
        "constituents": [{"security_code": "700", "return_1m": "0.1"}],
        "datasets": {
            "index_constituents": {"source_type": "UPLOAD"},
            "constituent_returns": {"source_type": "FMP_API"},
        },
    }
    assert not has_approved_constituent_bundle(payload)


def test_applying_constituent_identity_auto_populates_page_04_returns(client, monkeypatch):
    monkeypatch.setattr(settings, "fmp_constituent_returns_enabled", True)
    monkeypatch.setattr(settings, "fmp_api_key", "test-secret")

    def fake_load(constituents, report_date):
        assert report_date == date(2026, 6, 30)
        return {
            "constituent_returns": [{
                "security_code": row["security_code"],
                "return_1m": "0.01",
                "return_3m": "0.03",
                "return_6m": "0.06",
                "return_ytd": "0.08",
            } for row in constituents],
            "return_periods": {
                "starts": {
                    "return_1m": "2026-05-29",
                    "return_3m": "2026-03-31",
                    "return_6m": "2025-12-31",
                    "return_ytd": "2025-12-31",
                },
                "end": "2026-06-30",
                "source": "Financial Modeling Prep dividend-adjusted EOD",
            },
            "datasets": {"constituent_returns": {"source_type": "FMP_API"}},
            "_findings": [],
        }

    monkeypatch.setattr("app.domain.service.snapshots.load_constituent_returns", fake_load)
    report = client.post(
        "/api/v1/reports",
        json={"product_code": "3033", "report_date": "2026-06-30"},
    ).json()
    fixture = Path(__file__).parent / "fixtures" / "ingestion" / "index_constituents.csv"
    staged = client.post(
        f"/api/v1/reports/{report['id']}/imports",
        data={"dataset_type": "index_constituents"},
        files={"file": (fixture.name, fixture.read_bytes(), "text/csv")},
    )
    assert staged.status_code == 201, staged.text

    applied = client.post(
        f"/api/v1/reports/{report['id']}/imports/{staged.json()['id']}/apply",
        json={},
    )
    assert applied.status_code == 200, applied.text
    payload = applied.json()["payload"]
    assert payload["datasets"]["index_constituents"]["source_type"] == "UPLOAD"
    assert payload["datasets"]["constituent_returns"]["source_type"] == "FMP_API"
    assert all(row["return_1m"] == "0.01" for row in payload["constituents"])

    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    displayed = detail["latest_document"]["content"]["sections"]["constituents"]
    assert displayed
    assert all(row["return_ytd"] == "0.08" for row in displayed)
