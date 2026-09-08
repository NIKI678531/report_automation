"""Deterministic report localization shared by HTML, PDF, DOCX and API checks.

English identifiers and source names are never translated. Chinese display text prefers the
explicit target-script value, then uses OpenCC only between Simplified and Traditional Chinese.
An absent Chinese source stays absent; it is never silently replaced with English.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

from opencc import OpenCC


ZH_HANS = "ZH_HANS"
ZH_HANT = "ZH_HANT"

REPORT_TERMS: dict[str, tuple[str, str, str]] = {
    "monthly_commentary": ("Monthly Commentary", "月度评论", "月度評論"),
    "company_news": ("Company News", "公司新闻", "公司新聞"),
    "key_drivers": ("Key Drivers of the Correction", "市场调整的主要驱动因素", "市場調整的主要驅動因素"),
    "areas_to_monitor": ("Key Areas to Monitor", "重点关注领域", "重點關注領域"),
    "outlook": ("Outlook", "展望", "展望"),
    "historical_performance": ("Historical Performance of {product} and {benchmark}*", "{product} 与 {benchmark} 的历史表现*", "{product} 與 {benchmark} 的歷史表現*"),
    "constituent_performance": ("The Performance of {product} Constituents", "{product} 成分股表现", "{product} 成分股表現"),
    "next_rebalancing_date": ("*Next Rebalancing Date: {date}", "*下次再平衡日期：{date}", "*下次再平衡日期：{date}"),
    "stock_code": ("Stock Code", "股票代码", "股票代碼"),
    "stock_name": ("Stock Name", "股票名称", "股票名稱"),
    "closing_price_hkd": ("Closing Price (HKD)", "收市价（港元）", "收市價（港元）"),
    "weighting_pct": ("Weighting (%)", "权重（%）", "權重（%）"),
    "return_1m": ("1-month return (%)", "1个月回报（%）", "1個月回報（%）"),
    "return_3m": ("3-month return (%)", "3个月回报（%）", "3個月回報（%）"),
    "return_6m": ("6-month return (%)", "6个月回报（%）", "6個月回報（%）"),
    "return_ytd": ("YTD return (%)", "年初至今回报（%）", "年初至今回報（%）"),
    "top10": ("Top 10 {product} Constituents*", "{product} 十大成分股*", "{product} 十大成分股*"),
    "sector_breakdown": ("{product} Sectors Breakdown*", "{product} 行业分布*", "{product} 行業分佈*"),
    "top_performers": ("Top Performers in {month}**", "{month}表现最佳成份股**", "{month}表現最佳成份股**"),
    "bottom_performers": ("Bottom Performers in {month}**", "{month}表现最弱成份股**", "{month}表現最弱成份股**"),
    "issuer": ("Issuer", "发行人", "發行人"),
    "weight": ("Weight (%)", "权重（%）", "權重（%）"),
    "return": ("Return (%)", "回报（%）", "回報（%）"),
    "portfolio_analysis": ("{product} Portfolio Analysis", "{product} 投资组合分析", "{product} 投資組合分析"),
    "measure": ("Measure", "指标", "指標"),
    "value": ("Value", "数值", "數值"),
    "sector": ("Sector", "行业", "行業"),
    "no_data": ("N/A", "暂无数据", "暫無資料"),
    "testing_label": ("TESTING DATA - NOT FOR DISTRIBUTION", "测试数据 - 不得分发", "測試資料 - 不得分發"),
    "testing_watermark": ("TESTING", "测试", "測試"),
}

MONTHS_ZH = {
    1: "1月", 2: "2月", 3: "3月", 4: "4月", 5: "5月", 6: "6月",
    7: "7月", 8: "8月", 9: "9月", 10: "10月", 11: "11月", 12: "12月",
}

PORTFOLIO_LABELS = {
    ZH_HANS: {
        "AUM": "资产管理规模（百万港元）^",
        "AVERAGE_DAILY_TURNOVER": "平均每日成交额（百万港元）^^",
        "NUMBER_OF_HOLDINGS": "持仓数量",
    },
    ZH_HANT: {
        "AUM": "資產管理規模（百萬港元）^",
        "AVERAGE_DAILY_TURNOVER": "平均每日成交額（百萬港元）^^",
        "NUMBER_OF_HOLDINGS": "持倉數量",
    },
}


def is_zh_hans(language_mode: str | None) -> bool:
    return str(language_mode or "EN").upper() == ZH_HANS


def is_zh_hant(language_mode: str | None) -> bool:
    return str(language_mode or "EN").upper() == ZH_HANT


def is_chinese(language_mode: str | None) -> bool:
    return str(language_mode or "EN").upper() in {ZH_HANS, ZH_HANT}


def term(key: str, language_mode: str | None = "EN", **values: Any) -> str:
    english, simplified, traditional = REPORT_TERMS[key]
    value = traditional if is_zh_hant(language_mode) else simplified if is_zh_hans(language_mode) else english
    return value.format(**values)


@lru_cache(maxsize=1)
def _t2s_converter() -> OpenCC:
    return OpenCC("t2s")


def traditional_to_simplified(value: str | None) -> str:
    return _t2s_converter().convert(str(value or "")).strip()


@lru_cache(maxsize=1)
def _s2t_converter() -> OpenCC:
    return OpenCC("s2hk")


def simplified_to_traditional(value: str | None) -> str:
    return _s2t_converter().convert(str(value or "")).strip()


def localized_source_text(
    *,
    language_mode: str,
    en: str | None = None,
    zh_hans: str | None = None,
    zh_hant: str | None = None,
) -> tuple[str, str]:
    """Return display text and its auditable conversion status."""
    if not is_chinese(language_mode):
        return str(en or "").strip(), "SOURCE_EN" if en else "MISSING"
    if is_zh_hans(language_mode):
        if str(zh_hans or "").strip():
            return str(zh_hans).strip(), "SOURCE_ZH_HANS"
        if str(zh_hant or "").strip():
            return traditional_to_simplified(zh_hant), "OPENCC_T2S"
    else:
        if str(zh_hant or "").strip():
            return str(zh_hant).strip(), "SOURCE_ZH_HANT"
        if str(zh_hans or "").strip():
            return simplified_to_traditional(zh_hans), "OPENCC_S2T"
    return "", "MISSING"


def month_name(value: date, language_mode: str | None) -> str:
    return MONTHS_ZH[value.month] if is_chinese(language_mode) else value.strftime("%B")


def long_date(value: date, language_mode: str | None) -> str:
    if is_chinese(language_mode):
        return f"{value.year}年{value.month}月{value.day}日"
    return value.strftime("%B %d, %Y").replace(" 0", " ")


def short_date(value: date | None, language_mode: str | None) -> str:
    if value is None:
        return term("no_data", language_mode)
    if is_chinese(language_mode):
        return f"{value.year}年{value.month}月{value.day}日"
    return f"{value.day} {value.strftime('%B')} {value.year}"


def localized_portfolio_value(value: Any, language_mode: str | None) -> str:
    text = str(value or "")
    if is_chinese(language_mode) and text.endswith(" million"):
        return text.removesuffix(" million")
    return term("no_data", language_mode) if is_chinese(language_mode) and text == "N/A" else text


def localized_portfolio_label(metric_code: Any, fallback: Any, language_mode: str | None) -> str:
    labels = PORTFOLIO_LABELS.get(str(language_mode or "EN").upper())
    return str(labels.get(str(metric_code), fallback) if labels else fallback)


def localized_row_name(row: dict[str, Any], language_mode: str | None) -> tuple[str, str]:
    return localized_source_text(
        language_mode=str(language_mode or "EN"),
        en=row.get("name_en") or row.get("issuer") or row.get("sector"),
        zh_hans=row.get("name_zh_hans") or row.get("issuer_zh_hans") or row.get("sector_zh_hans"),
        zh_hant=row.get("name_zh_hant") or row.get("issuer_zh_hant") or row.get("sector_zh_hant"),
    )


def enrich_localized_names(payload: dict[str, Any]) -> dict[str, Any]:
    """Add deterministic Simplified and Traditional display fields without removing sources."""
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
        value, source = localized_source_text(
            language_mode=ZH_HANT,
            en=row.get("name_en"),
            zh_hans=row.get("name_zh_hans"),
            zh_hant=row.get("name_zh_hant"),
        )
        row["name_zh_hant"] = value
        row["name_zh_hant_source"] = source
        if row.get("effective_industry_name_zh_hant"):
            row.setdefault("effective_industry_name_zh_hant_source", "SOURCE_ZH_HANT")
        elif row.get("effective_industry_name_zh_hans"):
            row["effective_industry_name_zh_hant"] = simplified_to_traditional(
                row.get("effective_industry_name_zh_hans")
            )
            row["effective_industry_name_zh_hant_source"] = "OPENCC_S2T"
        else:
            row.setdefault("effective_industry_name_zh_hant", "")
            row.setdefault("effective_industry_name_zh_hant_source", "MISSING")
    return payload


def enrich_simplified_names(payload: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for callers predating Traditional Chinese output."""
    return enrich_localized_names(payload)


def chinese_content_warnings(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-blocking findings for editable Chinese prose that is intentionally left blank."""
    language_mode = str(document.get("language_mode") or "EN")
    if not is_chinese(language_mode):
        return []
    field_suffix = "zh_hant" if is_zh_hant(language_mode) else "zh_hans"
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
        if not str(item.get(f"name_{field_suffix}") or "").strip():
            missing.append(f"sections.constituents.{index}.name_{field_suffix}")
    sector_series = (((document.get("sections") or {}).get("analytics") or {}).get("sector_chart") or {}).get("series") or []
    for index, item in enumerate(sector_series):
        if not str(item.get(f"label_{field_suffix}") or "").strip():
            missing.append(f"sections.analytics.sector_chart.series.{index}.label_{field_suffix}")
    if (document.get("translation_provenance") or {}).get("product_name") == "MISSING":
        missing.append("product_name")
    if not missing:
        return []
    return [{
        "check_id": "LANG-ZH-001",
        "severity": "WARNING",
        "status": "WARNING",
        "actual": {"missing_fields": missing},
        "fix_hint": (
            "請補充缺失的繁體中文內容；當前內容可留空匯出，系統不會使用英文回退。"
            if is_zh_hant(language_mode)
            else "请补充缺失的简体中文内容；当前内容可留空导出，系统不会使用英文回退。"
        ),
    }]
