from decimal import Decimal

import pytest

from app.domain.metrics.errors import CalculationError
from app.domain.metrics.final_analytics import calculate_snapshot, normalize_portfolio_rows
from app.domain.metrics.footnotes import build_lineage_footnotes
from app.domain.metrics.historical_performance import period_return
from app.domain.metrics.industry_breakdown import sector_breakdown
from app.domain.metrics.quality_checks import snapshot_checks
from app.domain.service.snapshots import has_uploaded_constituent_bundle

# HSICS codes, as an aggregation key must be. `sector` alone is a raw source string and no longer
# satisfies `sector_breakdown` — QC-003 refuses it, so the chart must refuse it too.
IT = {"effective_industry_code": "70", "effective_industry_name": "Information Technology"}
CONSUMER = {"effective_industry_code": "23", "effective_industry_name": "Consumer Discretionary"}


def test_constituent_analysis_accepts_only_complete_upload_lineage():
    assert has_uploaded_constituent_bundle({
        "datasets": {"constituent_performance": {"source_type": "UPLOAD"}},
    })
    assert has_uploaded_constituent_bundle({
        "datasets": {
            "index_constituents": {"source_type": "UPLOAD"},
            "constituent_returns": {"source_type": "UPLOAD"},
        },
    })
    assert not has_uploaded_constituent_bundle({
        "datasets": {
            "index_constituents": {"source_type": "CDB"},
            "constituent_returns": {"source_type": "UPLOAD"},
        },
    })


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


def test_bottom_performers_display_from_smallest_to_largest_return():
    rows = [
        {"security_code": "100", "name_en": "Worst", "weight": 0.1, **IT, "return_1m": -0.50},
        {"security_code": "285", "name_en": "Second", "weight": 0.1, **IT, "return_1m": -0.28},
        {"security_code": "2382", "name_en": "Third", "weight": 0.1, **IT, "return_1m": -0.26},
        {"security_code": "700", "name_en": "Excluded", "weight": 0.7, **IT, "return_1m": -0.10},
    ]

    analytics, metrics = calculate_snapshot({"constituents": rows})

    assert [item["security_code"] for item in analytics["bottom"]] == ["100", "285", "2382"]
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
                "label_zh_hans": "",
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
                "label_zh_hans": "",
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
        "constituents": [{"security_code": "1", "name_en": "A", "weight": "1", **IT, "return_1m": "0"}],
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
    warning = next(item for item in snapshot_checks(base) if item["check_id"] == "KPI-002-PARTIAL-COVERAGE")
    assert warning["severity"] == "WARNING"
    assert warning["status"] == "FAILED"
    analytics, _ = calculate_snapshot(base)
    turnover_row = analytics["portfolio"][1]
    assert turnover_row["display_value"] == "10 million"
    assert turnover_row["as_of_date"] == "2026-06-19"
    assert turnover_row["coverage"] == "0.95"
    assert turnover_row["is_provisional"] is True
    base["fund_kpis"].pop()
    failed = next(item for item in snapshot_checks(base) if item["check_id"] == "KPI-002")
    assert failed["status"] == "FAILED"


def test_portfolio_amounts_are_normalized_to_millions_before_display_and_average():
    payload = {
        "as_of_date": "2026-06-30",
        "product_currency": "HKD",
        "constituents": [
            {"security_code": "1", "name_en": "A", "weight": "0.6", **IT, "return_1m": "0.1"},
            {"security_code": "2", "name_en": "B", "weight": "0.4", **CONSUMER, "return_1m": "-0.1"},
        ],
        "fund_kpis": [
            {"metric_code": "AUM", "metric_date": "2026-06-30", "value": "67536550000", "currency": "HKD", "unit": "unit"},
            {"metric_code": "DAILY_TURNOVER", "metric_date": "2026-06-29", "value": "12000000000", "currency": "HKD", "unit": "unit"},
            {"metric_code": "DAILY_TURNOVER", "metric_date": "2026-06-30", "value": "13.764", "currency": "HKD", "unit": "billion"},
            # Not an authoritative trading day, so it must not enter the mean.
            {"metric_code": "DAILY_TURNOVER", "metric_date": "2026-06-28", "value": "999999", "currency": "HKD", "unit": "billion"},
        ],
        "trading_calendar": [
            {"market": "HK", "date": "2026-06-28", "is_trading_day": False},
            {"market": "HK", "date": "2026-06-29", "is_trading_day": True},
            {"market": "HK", "date": "2026-06-30", "is_trading_day": True},
        ],
    }

    analytics, metrics = calculate_snapshot(payload)

    assert [row["display_value"] for row in analytics["portfolio"]] == [
        "67,536.55 million", "12,882 million", "2",
    ]
    assert analytics["portfolio"][0]["raw_value"] == "67536.55"
    assert analytics["portfolio"][1] == {
        "metric_code": "AVERAGE_DAILY_TURNOVER",
        "label": "Average Daily Turnover (HKD)^^",
        "raw_value": "12882.000",
        "currency": "HKD",
        "unit": "million",
        "display_precision": 0,
        "display_value": "12,882 million",
        "value": "12,882 million",
        "as_of_date": "2026-06-30",
        "observation_count": 2,
        "expected_day_count": 2,
        "coverage": "1",
        "is_provisional": False,
    }
    assert metrics["aum_value"] == "67536.55"
    assert metrics["aum_as_of_date"] == "2026-06-30"
    assert metrics["turnover_average"] == "12882.000"
    assert metrics["turnover_coverage"] == "1"


def test_duplicate_turnover_dates_fail_quality_and_are_not_averaged_twice():
    payload = {
        "as_of_date": "2026-06-30",
        "constituents": [{"security_code": "1", "name_en": "A", "weight": "1", **IT, "return_1m": "0"}],
        "fund_kpis": [
            {"metric_code": "AUM", "metric_date": "2026-06-30", "value": "100", "currency": "HKD", "unit": "million"},
            {"metric_code": "DAILY_TURNOVER", "metric_date": "2026-06-30", "value": "10", "currency": "HKD", "unit": "million"},
            {"metric_code": "DAILY_TURNOVER", "metric_date": "2026-06-30", "value": "20", "currency": "HKD", "unit": "million"},
        ],
        "trading_calendar": [{"market": "HK", "date": "2026-06-30", "is_trading_day": True}],
    }

    analytics, metrics = calculate_snapshot(payload)
    check = next(item for item in snapshot_checks(payload) if item["check_id"] == "KPI-002")

    assert check["status"] == "FAILED"
    assert check["actual"]["duplicate_days"] is True
    assert metrics["turnover_average"] is None
    assert [row["metric_code"] for row in analytics["portfolio"]] == [
        "AUM", "AVERAGE_DAILY_TURNOVER", "NUMBER_OF_HOLDINGS",
    ]
    assert analytics["portfolio"][1]["display_value"] == "N/A"
    assert analytics["portfolio"][1]["availability"] == "MISSING_SOURCE_DATA"


def test_portfolio_analysis_keeps_all_three_rows_when_fund_kpis_are_missing():
    analytics, metrics = calculate_snapshot({
        "as_of_date": "2026-08-31",
        "product_currency": "HKD",
        "constituents": [
            {"security_code": "1", "name_en": "A", "weight": "1", **IT, "return_1m": "0"},
        ],
    })

    assert [(row["metric_code"], row["label"], row["display_value"]) for row in analytics["portfolio"]] == [
        ("AUM", "Asset Under Management (HKD)^", "N/A"),
        ("AVERAGE_DAILY_TURNOVER", "Average Daily Turnover (HKD)^^", "N/A"),
        ("NUMBER_OF_HOLDINGS", "Number of holdings", "1"),
    ]
    assert metrics["aum_value"] is None
    assert metrics["turnover_average"] is None


def test_aum_uses_latest_same_month_date_independently_of_constituent_as_of_date():
    payload = {
        "report_date": "2026-05-31",
        "as_of_date": "2026-05-28",
        "product_currency": "HKD",
        "constituents": [
            {"security_code": "1", "name_en": "A", "weight": "1", **IT, "return_1m": "0"},
        ],
        "fund_kpis": [
            {"metric_code": "AUM", "metric_date": "2026-05-28", "value": "79000", "currency": "HKD", "unit": "million"},
            {"metric_code": "AUM", "metric_date": "2026-05-29", "value": "80291.57591427", "currency": "HKD", "unit": "million"},
            {"metric_code": "AUM", "metric_date": "2026-04-30", "value": "99999", "currency": "HKD", "unit": "million"},
        ],
    }

    analytics, metrics = calculate_snapshot(payload)
    check = next(item for item in snapshot_checks(payload) if item["check_id"] == "KPI-001")

    assert analytics["portfolio"][0]["display_value"] == "80,291.58 million"
    assert analytics["portfolio"][0]["as_of_date"] == "2026-05-29"
    assert metrics["aum_as_of_date"] == "2026-05-29"
    assert check["status"] == "PASSED"
    assert check["actual"]["report_date"] == "2026-05-31"
    assert check["actual"]["as_of_date"] == "2026-05-29"


def test_portfolio_normalizer_repairs_legacy_holding_only_documents():
    rows = normalize_portfolio_rows([{"label": "Number of holdings", "value": "30"}], "HKD")

    assert [row["metric_code"] for row in rows] == [
        "AUM", "AVERAGE_DAILY_TURNOVER", "NUMBER_OF_HOLDINGS",
    ]
    assert [row["display_value"] for row in rows] == ["N/A", "N/A", "30"]


@pytest.mark.parametrize(
    ("as_of_date", "trading_dates", "aum_value", "turnover_values", "expected"),
    [
        ("2024-02-29", ("2024-02-28", "2024-02-29"), "51234.10", ("8000", "9530"), ("51,234.10 million", "8,765 million")),
        ("2026-08-31", ("2026-08-28", "2026-08-31"), "72345.67", ("13000", "13420"), ("72,345.67 million", "13,210 million")),
        ("2030-12-31", ("2030-12-30", "2030-12-31"), "88000", ("14000", "15000"), ("88,000.00 million", "14,500 million")),
    ],
)
def test_portfolio_analysis_uses_the_selected_report_month(
    as_of_date, trading_dates, aum_value, turnover_values, expected,
):
    payload = {
        "as_of_date": as_of_date,
        "product_currency": "HKD",
        "constituents": [{"security_code": "1", "name_en": "A", "weight": "1", **IT, "return_1m": "0"}],
        "fund_kpis": [
            {"metric_code": "AUM", "metric_date": as_of_date, "value": aum_value, "currency": "HKD", "unit": "million"},
            *[
                {"metric_code": "DAILY_TURNOVER", "metric_date": metric_date, "value": value, "currency": "HKD", "unit": "million"}
                for metric_date, value in zip(trading_dates, turnover_values, strict=True)
            ],
        ],
        "trading_calendar": [
            {"market": "HK", "date": metric_date, "is_trading_day": True}
            for metric_date in trading_dates
        ],
    }

    analytics, _ = calculate_snapshot(payload)

    assert tuple(row["display_value"] for row in analytics["portfolio"][:2]) == expected
    assert analytics["portfolio"][0]["as_of_date"] == as_of_date


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
