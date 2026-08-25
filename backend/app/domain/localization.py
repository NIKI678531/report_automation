"""Deterministic report localization shared by HTML, PDF, DOCX and API checks.

English identifiers and source names are never translated.  Simplified Chinese display text
uses an explicit ``*_zh_hans`` value first, then OpenCC for an available Traditional Chinese
source.  An absent Chinese source stays absent; it is never silently replaced with English.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

from opencc import OpenCC


ZH_HANS = "ZH_HANS"

REPORT_TERMS: dict[str, tuple[str, str]] = {
    "monthly_commentary": ("Monthly Commentary", "月度评论"),
    "company_news": ("Company News", "公司新闻"),
    "key_drivers": ("Key Drivers of the Correction", "市场调整的主要驱动因素"),
    "areas_to_monitor": ("Key Areas to Monitor", "重点关注领域"),
    "outlook": ("Outlook", "展望"),
    "historical_performance": ("Historical Performance of {product} and {benchmark}*", "{product} 与 {benchmark} 的历史表现*"),
    "constituent_performance": ("The Performance of {index} Constituents", "{index} 成份股表现"),
    "next_rebalancing_date": ("*Next Rebalancing Date: {date}", "*下次再平衡日期：{date}"),
    "stock_code": ("Stock Code", "股票代码"),
    "stock_name": ("Stock Name", "股票名称"),
    "closing_price_hkd": ("Closing Price (HKD)", "收市价（港元）"),
    "weighting_pct": ("Weighting (%)", "权重（%）"),
    "return_1m": ("1-month return (%)", "1个月回报（%）"),
    "return_3m": ("3-month return (%)", "3个月回报（%）"),
    "return_6m": ("6-month return (%)", "6个月回报（%）"),
    "return_ytd": ("YTD return (%)", "年初至今回报（%）"),
    "top10": ("Top 10 Index Constituents*", "指数十大成份股*"),
    "sector_breakdown": ("Index Sectors Breakdown*", "指数行业分布*"),
    "top_performers": ("Top Performers in {month}**", "{month}表现最佳成份股**"),
    "bottom_performers": ("Bottom Performers in {month}**", "{month}表现最弱成份股**"),
    "issuer": ("Issuer", "发行人"),
    "weight": ("Weight (%)", "权重（%）"),
    "return": ("Return (%)", "回报（%）"),
    "portfolio_analysis": ("{product} Portfolio Analysis", "{product} 投资组合分析"),
    "measure": ("Measure", "指标"),
    "value": ("Value", "数值"),
    "sector": ("Sector", "行业"),
    "no_data": ("N/A", "暂无数据"),
    "testing_label": ("TESTING DATA - NOT FOR DISTRIBUTION", "测试数据 - 不得分发"),
    "testing_watermark": ("TESTING", "测试"),
}

MONTHS_ZH = {
    1: "1月", 2: "2月", 3: "3月", 4: "4月", 5: "5月", 6: "6月",
    7: "7月", 8: "8月", 9: "9月", 10: "10月", 11: "11月", 12: "12月",
}

PORTFOLIO_LABELS = {
    "aum": "资产管理规模（百万港元）",
    "average_daily_turnover": "平均每日成交额（百万港元）",
    "number_of_holdings": "持仓数量",
}


def is_zh_hans(language_mode: str | None) -> bool:
    return str(language_mode or "EN").upper() == ZH_HANS


def term(key: str, language_mode: str | None = "EN", **values: Any) -> str:
    english, chinese = REPORT_TERMS[key]
    return (chinese if is_zh_hans(language_mode) else english).format(**values)


@lru_cache(maxsize=1)
def _t2s_converter() -> OpenCC:
    return OpenCC("t2s")


def traditional_to_simplified(value: str | None) -> str:
    return _t2s_converter().convert(str(value or "")).strip()


def localized_source_text(
    *,
    language_mode: str,
    en: str | None = None,
    zh_hans: str | None = None,
    zh_hant: str | None = None,
) -> tuple[str, str]:
    """Return display text and its auditable conversion status."""
    if not is_zh_hans(language_mode):
        return str(en or "").strip(), "SOURCE_EN" if en else "MISSING"
    if str(zh_hans or "").strip():
        return str(zh_hans).strip(), "SOURCE_ZH_HANS"
    if str(zh_hant or "").strip():
        return traditional_to_simplified(zh_hant), "OPENCC_T2S"
    return "", "MISSING"


def month_name(value: date, language_mode: str | None) -> str:
    return MONTHS_ZH[value.month] if is_zh_hans(language_mode) else value.strftime("%B")


def long_date(value: date, language_mode: str | None) -> str:
    if is_zh_hans(language_mode):
        return f"{value.year}年{value.month}月{value.day}日"
    return value.strftime("%B %d, %Y").replace(" 0", " ")


def short_date(value: date | None, language_mode: str | None) -> str:
    if value is None:
        return term("no_data", language_mode)
    if is_zh_hans(language_mode):
        return f"{value.year}年{value.month}月{value.day}日"
    return f"{value.day} {value.strftime('%B')} {value.year}"


def localized_portfolio_value(value: Any, language_mode: str | None) -> str:
    text = str(value or "")
    if is_zh_hans(language_mode) and text.endswith(" million"):
        return text.removesuffix(" million")
    return term("no_data", language_mode) if is_zh_hans(language_mode) and text == "N/A" else text


def localized_row_name(row: dict[str, Any], language_mode: str | None) -> tuple[str, str]:
    return localized_source_text(
        language_mode=str(language_mode or "EN"),
        en=row.get("name_en") or row.get("issuer") or row.get("sector"),
        zh_hans=row.get("name_zh_hans") or row.get("issuer_zh_hans") or row.get("sector_zh_hans"),
        zh_hant=row.get("name_zh_hant") or row.get("issuer_zh_hant") or row.get("sector_zh_hant"),
    )


def enrich_simplified_names(payload: dict[str, Any]) -> dict[str, Any]:
    """Add deterministic Simplified Chinese display fields without removing source fields."""
    for row in payload.get("constituents") or []:
        value, source = localized_source_text(
            language_mode=ZH_HANS,
            en=row.get("name_en"),
            zh_hans=row.get("name_zh_hans"),
            zh_hant=row.get("name_zh_hant"),
        )
        row["name_zh_hans"] = value
        row["name_zh_hans_source"] = source
        if row.get("effective_industry_name_zh_hans"):
            row.setdefault("effective_industry_name_zh_hans_source", "SOURCE_ZH_HANS")
        elif row.get("effective_industry_name_zh_hant"):
            row["effective_industry_name_zh_hans"] = traditional_to_simplified(
                row.get("effective_industry_name_zh_hant")
            )
            row["effective_industry_name_zh_hans_source"] = "OPENCC_T2S"
        else:
            row.setdefault("effective_industry_name_zh_hans", "")
            row.setdefault("effective_industry_name_zh_hans_source", "MISSING")
    return payload


def chinese_content_warnings(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-blocking findings for editable Chinese prose that is intentionally left blank."""
    if not is_zh_hans(document.get("language_mode")):
        return []
    missing: list[str] = []
    review = (document.get("sections") or {}).get("month_in_review") or {}
    blocks = review.get("blocks") or []
    if blocks:
        missing.extend(
            f"sections.month_in_review.blocks.{index}.content"
            for index, block in enumerate(blocks)
            if not str(block.get("content") or "").strip()
        )
    else:
        missing.extend(
            f"sections.month_in_review.{field}"
            for field in ("summary", "outlook")
            if not str(review.get(field) or "").strip()
        )
    for index, item in enumerate((document.get("sections") or {}).get("company_news") or []):
        for field in ("title", "summary", "source_name"):
            if not str(item.get(field) or "").strip():
                missing.append(f"sections.company_news.{index}.{field}")
    for index, item in enumerate((document.get("sections") or {}).get("constituents") or []):
        if not str(item.get("name_zh_hans") or "").strip():
            missing.append(f"sections.constituents.{index}.name_zh_hans")
    sector_series = (((document.get("sections") or {}).get("analytics") or {}).get("sector_chart") or {}).get("series") or []
    for index, item in enumerate(sector_series):
        if not str(item.get("label_zh_hans") or "").strip():
            missing.append(f"sections.analytics.sector_chart.series.{index}.label_zh_hans")
    if (document.get("translation_provenance") or {}).get("product_name") == "MISSING":
        missing.append("product_name")
    if not missing:
        return []
    return [{
        "check_id": "LANG-ZH-001",
        "severity": "WARNING",
        "status": "WARNING",
        "actual": {"missing_fields": missing},
        "fix_hint": "请补充缺失的简体中文内容；当前内容可留空导出，系统不会使用英文回退。",
    }]
