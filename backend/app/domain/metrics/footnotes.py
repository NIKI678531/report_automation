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
    elif (payload.get("historical_performance") or {}).get("rows"):
        history = payload["historical_performance"]
        mapping = history.get("source_mapping") or {}
        fields = history.get("periods") or {}
        field_text = ", ".join(
            f"{label}={fields.get(output, {}).get('source_field', source)}"
            for output, source, label in (
                ("return_1m", "returns_l1m", "1M"),
                ("return_3m", "returns_l3m", "3M"),
                ("return_6m", "returns_l6m", "6M"),
                ("return_ytd", "returns_ytd", "YTD"),
            )
        )
        footnotes["historical"] = (
            f"Source: {history.get('source_name', 'CSOP Data Warehouse')}; "
            f"{mapping.get('tradar_code', '')} / {mapping.get('class_id', '')} and "
            f"{mapping.get('benchmark_index_ticker', '')}; as of {history.get('effective_as_of', as_of_date)}. "
            f"Source-supplied decimal period returns ({field_text}) are displayed as percentages."
        )

    datasets = payload.get("datasets", {})
    constituent_sources = []
    # Only real `ingestion.REGISTRY` slots. "constituents" and "final_analytics" used to be
    # listed here as well; neither has ever been a dataset type, so they could never match.
    for dataset_type in ("constituent_performance", "index_constituents"):
        source = datasets.get(dataset_type)
        if isinstance(source, dict):
            constituent_sources.append(str(source.get("filename") or source.get("import_id") or dataset_type))
    if constituent_sources:
        return_metadata = datasets.get("constituent_returns")
        return_source = None
        if isinstance(return_metadata, dict):
            return_source = (
                return_metadata.get("source_name")
                or (return_metadata.get("lineage") or {}).get("source_system")
                or return_metadata.get("filename")
                or return_metadata.get("source_object")
            )
        return_periods = payload.get("return_periods") or {}
        starts = return_periods.get("starts") or {}
        period_text = ", ".join(
            f"{label} {starts.get(field)} to {return_periods.get('end')}"
            for field, label in (("return_1m", "1M"), ("return_3m", "3M"), ("return_6m", "6M"), ("return_ytd", "YTD"))
            if starts.get(field) and return_periods.get("end")
        )
        taxonomy = payload.get("industry_master") or {}
        taxonomy_text = (
            f" HSICS {taxonomy.get('version')}." if taxonomy.get("version") else ""
        )
        footnotes["constituents"] = (
            f"Constituent source: {', '.join(sorted(set(constituent_sources)))}; as of {as_of_date}."
            f" Return source: {return_source or return_periods.get('source') or 'not recorded'}."
            f"{f' {period_text}.' if period_text else ''}{taxonomy_text}"
            " Prices, weights and returns retain their source units and periods."
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
