from decimal import Decimal

import pytest

from app.domain.metrics.errors import CalculationError
from app.domain.metrics.final_analytics import calculate_snapshot
from app.domain.metrics.footnotes import build_lineage_footnotes
from app.domain.metrics.historical_performance import period_return
from app.domain.metrics.industry_breakdown import sector_breakdown
from app.domain.metrics.quality_checks import snapshot_checks

# HSICS codes, as an aggregation key must be. `sector` alone is a raw source string and no longer
# satisfies `sector_breakdown` — QC-003 refuses it, so the chart must refuse it too.
IT = {"effective_industry_code": "70", "effective_industry_name": "Information Technology"}
CONSUMER = {"effective_industry_code": "23", "effective_industry_name": "Consumer Discretionary"}


def test_period_return_uses_total_return_ratio():
    assert period_return(Decimal("100"), Decimal("112.5")) == Decimal("0.125")


def test_period_return_rejects_nonpositive_start():
    with pytest.raises(ValueError):
        period_return(Decimal("0"), Decimal("1"))


def test_weight_rank_breaks_ties_on_ascending_security_code():
    rows = [
        {"security_code": "2", "name_en": "B", "weight": "0.5", **IT},
        {"security_code": "1", "name_en": "A", "weight": "0.5", **IT},
    ]

    analytics, _ = calculate_snapshot({"constituents": rows})

    assert [item["security_code"] for item in analytics["top10"]] == ["1", "2"]


def test_sector_breakdown_refuses_a_raw_source_sector_string():
    """An unmapped security cannot be aggregated into a chart that claims an HSICS taxonomy."""
    with pytest.raises(CalculationError) as error:
        sector_breakdown([{"security_code": "700", "weight": "1", "sector": "Information Technology"}])

    assert error.value.error_code == "INDUSTRY_MAPPING_MISSING"
    assert error.value.entity_id == "700"


def test_snapshot_checks_block_bad_weight_and_count():
    results = snapshot_checks({"constituents": [{"security_code": "1", "weight": 0.5, "sector": "IT"}]}, expected_constituent_count=30)
    failed = {item["check_id"] for item in results if item["status"] == "FAILED"}
    assert {"QC-002", "QC-HOLDING-COUNT"}.issubset(failed)
    count_check = next(item for item in results if item["check_id"] == "QC-HOLDING-COUNT")
    assert count_check["severity"] == "WARNING"


def test_snapshot_checks_use_spec_ids_for_industry_dates_and_return_basis():
    payload = {
        "as_of_date": "2026-06-30",
        "constituents": [{"security_code": "1", "weight": 1, "sector": None, "as_of_date": "2026-07-01"}],
        "total_return_series": [
            {"series_type": "PRICE RETURN", "currency": "HKD"},
        ],
        "historical_performance": {"rows": [{"return_1m": None}]},
    }
    failed = {item["check_id"] for item in snapshot_checks(payload) if item["status"] == "FAILED"}
    assert {"QC-003", "QC-004", "QC-005", "QC-006"}.issubset(failed)


def test_bottom_selection_and_display_order_are_separate():
    rows = [
        {"security_code": "100", "name_en": "Worst", "weight": 0.1, **IT, "return_1m": -0.50},
        {"security_code": "285", "name_en": "Second", "weight": 0.1, **IT, "return_1m": -0.28},
        {"security_code": "2382", "name_en": "Third", "weight": 0.1, **IT, "return_1m": -0.26},
        {"security_code": "700", "name_en": "Excluded", "weight": 0.7, **IT, "return_1m": -0.10},
    ]

    analytics, metrics = calculate_snapshot({"constituents": rows})

    assert [item["security_code"] for item in analytics["bottom"]] == ["2382", "285", "100"]
    assert metrics["bottom_security_code"] == "100"


def test_sector_chart_snapshot_freezes_backend_order_and_angles():
    """Order, angles, display string and colour token are all decided here, not in a renderer."""
    rows = [
        {"security_code": "1", "name_en": "A", "weight": "0.6", **IT, "return_1m": "0.1"},
        {"security_code": "2", "name_en": "B", "weight": "0.4", **CONSUMER, "return_1m": "0.2"},
    ]

    analytics, _ = calculate_snapshot({"constituents": rows})

    chart = analytics["sector_chart"]
    assert chart["chart_code"] == "industry_breakdown"
    assert chart["chart_type"] == "donut"
    assert len(chart["input_checksum"]) == 64
    # No template display order is configured for this payload, so the fallback applies:
    # weight-descending with an ascending-code tie-breaker (SORT-001).
    assert chart["series"] == [
        {
            "code": "70",
            "label": "Information Technology",
            "raw_value": "0.6",
            "unit": "RATIO",
            "display_value": "60.0%",
            "sort_order": 1,
            "color_token": "industry.hsics.70",
            "start_angle": "0",
            "end_angle": "216.0",
        },
        {
            "code": "23",
            "label": "Consumer Discretionary",
            "raw_value": "0.4",
            "unit": "RATIO",
            "display_value": "40.0%",
            "sort_order": 2,
            "color_token": "industry.hsics.23",
            "start_angle": "216.0",
            "end_angle": "360",
        },
    ]


def test_turnover_coverage_uses_authoritative_trading_days_and_95_percent_threshold():
    base = {
        "as_of_date": "2026-06-30",
        "constituents": [{"security_code": "1", "weight": "1", **IT}],
        "fund_kpis": [
            {"metric_code": "AUM", "metric_date": "2026-06-30", "value": "100", "currency": "HKD", "unit": "million"},
            *[
                {"metric_code": "DAILY_TURNOVER", "metric_date": f"2026-06-{day:02d}", "value": "10", "currency": "HKD", "unit": "million"}
                for day in range(1, 20)
            ],
        ],
        "trading_calendar": [
            {"market": "HK", "date": f"2026-06-{day:02d}", "is_trading_day": True}
            for day in range(1, 21)
        ],
    }
    passed = next(item for item in snapshot_checks(base) if item["check_id"] == "KPI-002")
    assert passed["status"] == "PASSED"
    assert passed["actual"]["coverage"] == "0.95"
    base["fund_kpis"].pop()
    failed = next(item for item in snapshot_checks(base) if item["check_id"] == "KPI-002")
    assert failed["status"] == "FAILED"


def test_next_rebalancing_date_comes_from_the_next_matching_index_event():
    payload = {
        "as_of_date": "2026-06-30",
        "constituent_index_code": "HSTECH",
        "constituents": [{"security_code": "1", "name_en": "A", "weight": "1", **IT, "return_1m": "0"}],
        "index_events": [
            {"index_code": "HSI", "event_type": "REBALANCE", "effective_date": "2026-07-01"},
            {"index_code": "HSTECH", "event_type": "REBALANCE", "effective_date": "2026-09-04"},
            {"index_code": "HSTECH", "event_type": "REBALANCE", "effective_date": "2026-12-04"},
        ],
    }
    _, metrics = calculate_snapshot(payload)
    assert metrics["next_rebalancing_date"] == "2026-09-04"


def test_footnotes_are_generated_from_actual_periods_sources_and_coverage():
    payload = {
        "as_of_date": "2026-06-30",
        "total_return_series": [{"source": "Approved TR"}],
        "historical_performance": {"periods": {"return_1m": {"period_start": "2026-05-29", "period_end": "2026-06-30"}}},
        "datasets": {"index_constituents": {"filename": "index.csv"}},
        "industry_master": {"version": "HSICS-2026-112"},
        "fund_kpis": [{"source": "Approved KPI"}],
    }
    metrics = {"turnover_observation_count": 19, "turnover_expected_day_count": 20, "turnover_coverage": "0.95"}

    footnotes = build_lineage_footnotes(payload, metrics)

    assert "2026-05-29 to 2026-06-30" in footnotes["historical"]
    assert "index.csv" in footnotes["constituents"]
    assert "HSICS-2026-112" in footnotes["constituents"]
    assert "19/20 (95.00%)" in footnotes["analytics"]
