"""The `industry_breakdown` chart snapshot contract (rules document §4.3).

The chart is structured data, never a screenshot, and it is the single place where ordering,
the zero-weight filter, the percentage string and the colour identity are decided. Three
renderers -- canonical HTML/PDF, DOCX and the React workbench -- consume it, so anything these
tests do not pin down is free to drift between formats.
"""
from decimal import Decimal

from app.domain.metrics.final_analytics import calculate_snapshot
from app.domain.metrics.industry_breakdown import (
    INDUSTRY_DISPLAY_ORDER,
    sector_breakdown,
    sector_chart_snapshot,
)

HSTECH_PROFILE = "hstech-2026.1"

REQUIRED_SNAPSHOT_FIELDS = (
    "schema_version", "chart_code", "chart_type", "snapshot_id", "snapshot_dataset_ids",
    "formula_version", "mapping_version", "taxonomy", "taxonomy_version", "as_of_date",
    "series", "input_checksum", "alt_text",
)
REQUIRED_SERIES_FIELDS = (
    "code", "label", "raw_value", "unit", "display_value", "sort_order", "color_token",
    "start_angle", "end_angle",
)


def constituent(code: str, industry: str, name: str, weight: str) -> dict:
    return {
        "security_code": code,
        "name_en": f"Security {code}",
        "weight": weight,
        "sector": name,
        "effective_industry_code": industry,
        "effective_industry_name": name,
        "return_1m": "0.01",
    }


def test_snapshot_carries_every_traceability_field_the_contract_requires():
    payload = {
        "constituents": [constituent("1", "70", "Information Technology", "1")],
        "as_of_date": "2026-06-30",
        "snapshot_id": "snap-1",
        "mapping_version": "hstech-v1",
        "formula_version": HSTECH_PROFILE,
        "snapshot_dataset_ids": {"constituent_snapshot": "ds-1", "industry_master": "ds-2", "unrelated": "ds-3"},
        "industry_master": {"taxonomy": "HSICS", "version": "HSICS-2026-112"},
    }

    chart = calculate_snapshot(payload)[0]["sector_chart"]

    assert set(REQUIRED_SNAPSHOT_FIELDS).issubset(chart)
    assert chart["chart_code"] == "industry_breakdown"
    assert chart["snapshot_id"] == "snap-1"
    assert chart["mapping_version"] == "hstech-v1"
    assert chart["formula_version"] == HSTECH_PROFILE
    assert chart["taxonomy"] == "HSICS"
    assert chart["taxonomy_version"] == "HSICS-2026-112"
    assert chart["as_of_date"] == "2026-06-30"
    # Only the datasets this chart actually reads, so lineage stays auditable.
    assert chart["snapshot_dataset_ids"] == ["ds-1", "ds-2"]
    assert set(REQUIRED_SERIES_FIELDS).issubset(chart["series"][0])


def test_zero_weight_industries_never_reach_the_series():
    sectors = [
        {"code": "70", "sector": "Information Technology", "weight": "0.6"},
        {"code": "10", "sector": "Industrials", "weight": "0"},
        {"code": "23", "sector": "Consumer Discretionary", "weight": "0.4"},
    ]

    chart = sector_chart_snapshot(sectors)

    assert [row["code"] for row in chart["series"]] == ["70", "23"]
    # The filter must not leave a gap in the ring: the remaining slices still span 360 degrees.
    assert chart["series"][0]["start_angle"] == "0"
    assert chart["series"][-1]["end_angle"] == "360"


def test_colour_is_bound_to_the_industry_not_to_its_position():
    """A positional colour index repainted an industry whenever the constituent set changed."""
    first = sector_chart_snapshot([
        {"code": "23", "sector": "Consumer Discretionary", "weight": "0.6"},
        {"code": "70", "sector": "Information Technology", "weight": "0.4"},
    ])
    second = sector_chart_snapshot([
        {"code": "28", "sector": "Healthcare", "weight": "0.5"},
        {"code": "70", "sector": "Information Technology", "weight": "0.3"},
        {"code": "23", "sector": "Consumer Discretionary", "weight": "0.2"},
    ])

    tokens = {row["code"]: row["color_token"] for chart in (first, second) for row in chart["series"]}
    assert tokens["70"] == "industry.hsics.70"
    assert {row["color_token"] for row in second["series"]} == {
        "industry.hsics.28", "industry.hsics.70", "industry.hsics.23",
    }
    # Same industry, different neighbours, same token.
    assert first["series"][1]["color_token"] == second["series"][1]["color_token"]


def test_display_order_comes_from_versioned_configuration_not_from_weight():
    """The reference legend runs Consumer Discretionary before the larger Information Technology."""
    rows = [
        constituent("1", "70", "Information Technology", "0.4927"),
        constituent("2", "23", "Consumer Discretionary", "0.4775"),
        constituent("3", "28", "Healthcare", "0.0170"),
        constituent("4", "10", "Industrials", "0.0128"),
    ]

    configured = sector_breakdown(rows, INDUSTRY_DISPLAY_ORDER[HSTECH_PROFILE])
    unconfigured = sector_breakdown(rows)

    assert [row["code"] for row in configured] == ["23", "70", "28", "10"]
    # Without configuration the fallback is weight-descending, so the order genuinely differs.
    assert [row["code"] for row in unconfigured] == ["70", "23", "28", "10"]


def test_financials_uses_the_confirmed_hstech_code_and_stable_color_token():
    rows = [constituent("1", "50", "Financials", "1")]

    chart = calculate_snapshot({"constituents": rows, "formula_version": HSTECH_PROFILE})[0]["sector_chart"]

    assert chart["series"][0]["code"] == "50"
    assert chart["series"][0]["label"] == "Financials"
    assert chart["series"][0]["color_token"] == "industry.hsics.50"


def test_unconfigured_industries_sort_after_configured_ones_deterministically():
    rows = [
        constituent("1", "99", "Utilities", "0.5"),
        constituent("2", "23", "Consumer Discretionary", "0.1"),
        constituent("3", "88", "Energy", "0.4"),
    ]

    ordered = sector_breakdown(rows, ["23", "70"])

    assert [row["code"] for row in ordered] == ["23", "99", "88"]


def test_display_value_is_the_single_rendered_percentage_at_one_decimal():
    rows = [
        constituent("1", "23", "Consumer Discretionary", "0.47753470631"),
        constituent("2", "70", "Information Technology", "0.49266295559"),
        constituent("3", "28", "Healthcare", "0.0170031541"),
        constituent("4", "10", "Industrials", "0.01279918399"),
    ]

    chart = calculate_snapshot({"constituents": rows, "formula_version": HSTECH_PROFILE})[0]["sector_chart"]

    assert [row["display_value"] for row in chart["series"]] == ["47.8%", "49.3%", "1.7%", "1.3%"]
    # Full precision survives alongside the rounded string, and rounding never feeds an angle.
    assert chart["series"][0]["raw_value"] == "0.47753470631"
    assert sum(Decimal(row["end_angle"]) - Decimal(row["start_angle"]) for row in chart["series"]) == Decimal("360")


def test_every_output_format_reads_the_same_display_value(client, tmp_path):
    """HTML, DOCX and the API response must not each format the percentage their own way."""
    import docx

    report = client.post("/api/v1/reports", json={"report_date": "2026-06-30"}).json()
    client.post(
        f"/api/v1/reports/{report['id']}/snapshots",
        json={"source_policy": "GOLDEN_FIXTURE", "mapping_version": "hstech-v1"},
    )
    client.post(f"/api/v1/reports/{report['id']}/calculations")
    detail = client.get(f"/api/v1/reports/{report['id']}").json()
    series = detail["latest_document"]["content"]["sections"]["analytics"]["sector_chart"]["series"]
    expected = [row["display_value"] for row in series]
    assert expected == ["47.8%", "49.3%", "1.7%", "1.3%"]

    client.post(f"/api/v1/reports/{report['id']}/finalize", json={"version": detail["version"]})
    rendered = client.post(
        f"/api/v1/reports/{report['id']}/renders",
        json={"formats": ["html", "docx"]},
        headers={"Idempotency-Key": "chart-contract"},
    ).json()

    artifacts = {}
    for job in rendered:
        signed = client.get(f"/api/v1/artifacts/{job['artifact_id']}/download").json()
        artifacts[job["format"]] = client.get(signed["download_url"]).content

    html = artifacts["html"].decode("utf-8")
    for value in expected:
        assert value in html

    docx_path = tmp_path / "actual.docx"
    docx_path.write_bytes(artifacts["docx"])
    docx_text = "\n".join(
        cell.text
        for table in docx.Document(str(docx_path)).tables
        for row in table.rows
        for cell in row.cells
    )
    for value in expected:
        assert value in docx_text
    assert "47.75%" not in docx_text and "49.27%" not in docx_text
