"""Report module 06 — Footnotes & Disclosures.

Each footnote is generated from the effective source, date, period and formula lineage of the
module it is bound to (QC-007). Nothing here is transcribed prose.
"""

from decimal import Decimal


def build_lineage_footnotes(payload: dict, metrics: dict | None = None) -> dict[str, str]:
    footnotes = dict(payload.get("footnotes") or {})
    as_of_date = str(payload.get("as_of_date") or "")
    series = payload.get("total_return_series", [])
    periods = payload.get("historical_performance", {}).get("periods", {})
    if series and periods:
        sources = ", ".join(sorted({str(row.get("source")) for row in series if row.get("source")}))
        period_labels = []
        for field, label in (("return_1m", "1M"), ("return_3m", "3M"), ("return_6m", "6M"), ("return_ytd", "YTD")):
            period = periods.get(field, {})
            if period.get("period_start") and period.get("period_end"):
                period_labels.append(f"{label} {period['period_start']} to {period['period_end']}")
        footnotes["historical"] = f"Source: {sources}; official Total Return series. {'; '.join(period_labels)}."

    datasets = payload.get("datasets", {})
    constituent_sources = []
    # Only real `ingestion.REGISTRY` slots. "constituents" and "final_analytics" used to be
    # listed here as well; neither has ever been a dataset type, so they could never match.
    for dataset_type in ("constituent_performance", "index_constituents"):
        source = datasets.get(dataset_type)
        if isinstance(source, dict):
            constituent_sources.append(str(source.get("filename") or source.get("import_id") or dataset_type))
    if constituent_sources:
        taxonomy = payload.get("industry_master") or {}
        taxonomy_text = (
            f" HSICS {taxonomy.get('version')}." if taxonomy.get("version") else ""
        )
        footnotes["constituents"] = (
            f"Source: {', '.join(sorted(set(constituent_sources)))}; as of {as_of_date}."
            f"{taxonomy_text} Prices, weights and returns retain their source units and periods."
        )

    fund_kpis = payload.get("fund_kpis", [])
    if fund_kpis:
        sources = ", ".join(sorted({str(row.get("source")) for row in fund_kpis if row.get("source")}))
        metric_values = metrics or {}
        observed = metric_values.get("turnover_observation_count", 0)
        expected = metric_values.get("turnover_expected_day_count", 0)
        coverage = metric_values.get("turnover_coverage")
        coverage_text = f" turnover coverage {observed}/{expected} ({Decimal(str(coverage)) * Decimal('100'):.2f}%)" if coverage is not None else ""
        taxonomy = payload.get("industry_master") or {}
        taxonomy_text = f" Industry aggregation uses HSICS {taxonomy.get('version')}." if taxonomy.get("version") else ""
        footnotes["analytics"] = (
            f"Source: {sources}; AUM as of {as_of_date};{coverage_text}."
            f"{taxonomy_text} Number of holdings counts unique positive-weight securities."
        )
    return footnotes
