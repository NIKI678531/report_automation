"""The golden fixture must be *derived*, not restated.

`snapshot.json` holds observations; `expected.json` holds the numbers the approved June 2026 report
prints. These tests drive the real lifecycle over the first and compare against the second. The
point is the gap between the two files: before this suite the payload carried its own answers, so
the pipeline could return them untouched and every assertion still passed.

That makes :func:`test_the_fixture_payload_states_no_answers` the load-bearing test here. The
comparisons below only mean something while the payload contains nothing to copy.
"""
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "3033_202606"
EXPECTED = json.loads((FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))
PAYLOAD = json.loads((FIXTURE_DIR / "snapshot.json").read_text(encoding="utf-8"))


def pct(value, places: int = 2) -> Decimal:
    """A ratio as the report prints it: percent, rounded half-up to `places`."""
    return (Decimal(str(value)) * Decimal("100")).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


@pytest.fixture
def derived(client) -> dict:
    """The document content the pipeline produces from the fixture, with nothing hand-fed."""
    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    snapshot = client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    assert snapshot.status_code == 201, snapshot.text
    calculated = client.post(f"/api/v1/reports/{report['id']}/calculations")
    assert calculated.status_code in (200, 201), calculated.text
    return client.get(f"/api/v1/reports/{report['id']}").json()["latest_document"]["content"]


def test_the_fixture_payload_states_no_answers():
    """The input file may not contain a single derived value.

    Every key listed here was in `snapshot.json` at some point, sitting next to the observations it
    was supposed to be computed from. `calculate_snapshot` and `build_lineage_footnotes` both used
    to read their own output back out of the payload, so the fixture could satisfy this repository's
    entire regression suite while the calculation layer did nothing.
    """
    forbidden = {
        "historical_performance": "derived by calculation.historical_performance from total_return_series",
        "analytics": "derived by calculation.calculate_snapshot from constituents and fund_kpis",
        "footnotes": "derived by calculation.build_lineage_footnotes from datasets and periods",
        "metrics": "derived by calculation.calculate_snapshot",
        "next_rebalancing_date": "derived by calculation.calculate_snapshot from index_events",
    }
    present = {key: why for key, why in forbidden.items() if key in PAYLOAD}
    assert not present, f"snapshot.json states answers instead of observations: {present}"


def test_the_synthetic_series_admits_what_it_is():
    """The one input that cannot be honest is at least labelled.

    No Total Return level series exists for either leg, so these rows are back-solved from the
    report's own returns and `historical_performance` is an identity on them. That is recorded on
    every row and on the expectation, so no future reader mistakes the match for evidence.
    """
    rows = PAYLOAD["total_return_series"]
    assert rows and all(row["synthetic"] is True for row in rows)
    assert {row["source"] for row in rows} == {"SYNTHETIC_BACK_SOLVED"}
    assert EXPECTED["historical_performance"]["circular"] is True


def test_historical_performance_reproduces_the_published_table(derived):
    """Self-consistency only -- see the circularity note on the expectation."""
    rows = {row["role"]: row for row in derived["sections"]["historical_performance"]["rows"]}
    for expected_row in EXPECTED["historical_performance"]["rows"]:
        actual = rows[expected_row["role"]]
        assert actual["name"] == expected_row["name"]
        for field in ("return_1m", "return_3m", "return_6m", "return_ytd"):
            assert pct(actual[field]) == pct(expected_row[field]), f"{expected_row['role']} {field}"


def test_top_ten_holdings_match_the_published_weights(derived):
    """Genuinely derived: the weights come from the index CSV, the order from the calculation."""
    actual = derived["sections"]["analytics"]["top10"]
    expected = EXPECTED["analytics"]["top10"]
    assert [row["security_code"] for row in actual] == [row["security_code"] for row in expected]
    assert [pct(row["weight"]) for row in actual] == [Decimal(str(row["weight_pct"])) for row in expected]


def test_sector_breakdown_matches_the_published_donut(derived):
    """Order, label and the one-decimal string are all decided in the backend."""
    actual = derived["sections"]["analytics"]["sector_chart"]["series"]
    expected = EXPECTED["analytics"]["sectors"]
    assert [row["code"] for row in actual] == [row["code"] for row in expected]
    assert [row["label"] for row in actual] == [row["label"] for row in expected]
    assert [row["display_value"] for row in actual] == [row["display_value"] for row in expected]


@pytest.mark.parametrize("block", ["top", "bottom"])
def test_performer_tables_match_the_published_returns(derived, block):
    """Selection and display order are separate steps, and the report pins both."""
    actual = derived["sections"]["analytics"][block]
    expected = EXPECTED["analytics"][block]
    assert [row["security_code"] for row in actual] == [row["security_code"] for row in expected]
    assert [pct(row["return"]) for row in actual] == [Decimal(str(row["return_1m_pct"])) for row in expected]


def test_portfolio_analysis_matches_the_published_block(derived):
    """Including the formatting: the report prints turnover with no decimals and AUM with two."""
    assert derived["sections"]["analytics"]["portfolio"] == EXPECTED["analytics"]["portfolio"]


def test_next_rebalancing_date_is_derived_from_the_index_event(derived):
    assert derived["next_rebalancing_date"] == EXPECTED["next_rebalancing_date"]
