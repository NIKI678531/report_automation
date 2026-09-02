"""Report module 06 — Footnotes & Disclosures.

Each footnote is generated from the effective source, date, period and formula lineage of the
module it is bound to (QC-007). Nothing here is transcribed prose.
"""

from decimal import Decimal

from .fund_kpis import monthly_turnover_rows, trading_days, turnover_rows
from ..localization import is_chinese, is_zh_hant, simplified_to_traditional


def _chinese(value: str, language_mode: str) -> str:
    return simplified_to_traditional(value) if is_zh_hant(language_mode) else value


def build_lineage_footnotes(
    payload: dict,
    metrics: dict | None = None,
    *,
    language_mode: str = "EN",
) -> dict[str, str]:
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
                separator = "至" if is_chinese(language_mode) else "to"
                period_labels.append(f"{label} {period['period_start']} {separator} {period['period_end']}")
        footnotes["historical"] = (
            _chinese(f"来源：{sources}；官方总回报序列。{'; '.join(period_labels)}。", language_mode)
            if is_chinese(language_mode)
            else f"Source: {sources}; official Total Return series. {'; '.join(period_labels)}."
        )
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
        if is_chinese(language_mode):
            footnotes["historical"] = _chinese((
                f"来源：{history.get('source_name', 'CSOP Data Warehouse')}；"
                f"{mapping.get('tradar_code', '')} / {mapping.get('class_id', '')} 及 "
                f"{mapping.get('benchmark_index_ticker', '')}；截至 {history.get('effective_as_of', as_of_date)}。"
                f"来源提供的小数形式期间回报（{field_text}）以百分比显示。"
            ), language_mode)
        else:
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
            f"{label} {starts.get(field)} {'至' if is_chinese(language_mode) else 'to'} {return_periods.get('end')}"
            for field, label in (("return_1m", "1M"), ("return_3m", "3M"), ("return_6m", "6M"), ("return_ytd", "YTD"))
            if starts.get(field) and return_periods.get("end")
        )
        taxonomy = payload.get("industry_master") or {}
        taxonomy_text = (
            f" HSICS {taxonomy.get('version')}." if taxonomy.get("version") else ""
        )
        if is_chinese(language_mode):
            footnotes["constituents"] = _chinese((
                f"成份股来源：{', '.join(sorted(set(constituent_sources)))}；截至 {as_of_date}。"
                f" 回报来源：{return_source or return_periods.get('source') or '未记录'}。"
                f"{f' {period_text}。' if period_text else ''}{taxonomy_text}"
                " 价格、权重及回报沿用来源单位与期间。"
            ), language_mode)
        else:
            footnotes["constituents"] = (
                f"Constituent source: {', '.join(sorted(set(constituent_sources)))}; as of {as_of_date}."
                f" Return source: {return_source or return_periods.get('source') or 'not recorded'}."
                f"{f' {period_text}.' if period_text else ''}{taxonomy_text}"
                " Prices, weights and returns retain their source units and periods."
            )

    fund_kpis = payload.get("fund_kpis", [])
    monthly_turnover = monthly_turnover_rows(payload, str(payload.get("report_date") or as_of_date))
    if fund_kpis or monthly_turnover:
        sources = ", ".join(sorted({
            str(row.get("source"))
            for row in [*fund_kpis, *monthly_turnover]
            if row.get("source")
        }))
        metric_values = metrics or {}
        observed = metric_values.get("turnover_observation_count", 0)
        expected = metric_values.get("turnover_expected_day_count", 0)
        coverage = metric_values.get("turnover_coverage")
        coverage_text = f" turnover coverage {observed}/{expected} ({Decimal(str(coverage)) * Decimal('100'):.2f}%)" if coverage is not None else ""
        aum_as_of_date = metric_values.get("aum_as_of_date") or as_of_date
        observed_turnover_rows = turnover_rows(fund_kpis, trading_days(payload))
        turnover_as_of_date = (
            str(monthly_turnover[0].get("period_end"))
            if len(monthly_turnover) == 1
            else max((str(row.get("metric_date")) for row in observed_turnover_rows), default=None)
        )
        is_partial = coverage is not None and Decimal(str(coverage)) < Decimal("1")
        turnover_date_text = (
            f" turnover through {turnover_as_of_date};"
            if turnover_as_of_date and is_partial else ""
        )
        taxonomy = payload.get("industry_master") or {}
        taxonomy_text = f" Industry aggregation uses HSICS {taxonomy.get('version')}." if taxonomy.get("version") else ""
        if is_chinese(language_mode):
            zh_turnover_date = f" 成交额截至 {turnover_as_of_date}；" if turnover_as_of_date and is_partial else ""
            zh_coverage = f" 成交额覆盖 {observed}/{expected}（{Decimal(str(coverage)) * Decimal('100'):.2f}%）" if coverage is not None else ""
            zh_taxonomy = f" 行业汇总采用 HSICS {taxonomy.get('version')}。" if taxonomy.get("version") else ""
            footnotes["analytics"] = _chinese((
                f"来源：{sources}；资产管理规模截至 {aum_as_of_date}；{zh_turnover_date}{zh_coverage}。"
                f"{zh_taxonomy} 持仓数量按权重大于零的唯一证券计算。"
            ), language_mode)
        else:
            footnotes["analytics"] = (
                f"Source: {sources}; AUM as of {aum_as_of_date};{turnover_date_text}{coverage_text}."
                f"{taxonomy_text} Number of holdings counts unique positive-weight securities."
            )
    return footnotes
