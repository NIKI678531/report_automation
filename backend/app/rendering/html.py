from __future__ import annotations

import base64
import json
import math
from copy import deepcopy
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.domain.document import review_display_title
from app.domain.localization import (
    ZH_HANS,
    is_chinese,
    is_zh_hans,
    is_zh_hant,
    localized_portfolio_label,
    localized_row_name,
    localized_portfolio_value,
    long_date as localized_long_date,
    month_name,
    short_date,
    simplified_to_traditional,
    term,
    traditional_to_simplified,
)
from app.domain.metrics.final_analytics import normalize_portfolio_rows
from app.domain.models import Report

ROOT = Path(__file__).resolve().parent
env = Environment(
    loader=FileSystemLoader(ROOT / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=StrictUndefined,
)


def pct(value: Decimal | float | int | str | None, language_mode: str = "EN") -> str:
    return term("no_data", language_mode) if value is None else f"{Decimal(str(value)) * Decimal('100'):.2f}"


def price(value: Decimal | float | int | str | None, language_mode: str = "EN") -> str:
    if value is None:
        return term("no_data", language_mode)
    return f"{Decimal(str(value)):.2f}".rstrip("0").rstrip(".")


def long_date(value: date, language_mode: str = "EN") -> str:
    return localized_long_date(value, language_mode)


def rebalancing_date_text(value: Any, language_mode: str = "EN") -> str:
    if not value:
        return term("no_data", language_mode)
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return term("no_data", language_mode)
    return short_date(parsed, language_mode)


env.filters.update(pct=pct, price=price, rebalancing_date=rebalancing_date_text)


_LEGACY_PREVIEW_PLACEHOLDERS = {
    "Add monthly market review.",
    "Add outlook.",
    "Add the approved monthly market review.",
    "Add the approved outlook.",
}


def _preview_document(report: Report, document: dict[str, Any]) -> dict[str, Any]:
    """Return a render-only, structurally complete copy of an unfinished document.

    Preview must be useful before every report module is populated, but it must not persist
    invented content or weaken the release gate.  The normalizer therefore fills only container
    shapes and identity defaults; staged uploads remain outside the document until they are
    explicitly applied through the snapshot workflow.
    """
    result = deepcopy(document) if isinstance(document, dict) else {}
    result.setdefault("report_date", report.report_date.isoformat())
    result.setdefault("month_name", report.report_date.strftime("%B"))
    result.setdefault("product_ticker", f"{report.product_code}.HK")
    result.setdefault("benchmark_name", report.benchmark_code)

    sections = result.get("sections")
    if not isinstance(sections, dict):
        sections = {}
        result["sections"] = sections

    review = sections.get("month_in_review")
    if not isinstance(review, dict):
        review = {}
        sections["month_in_review"] = review
    review.setdefault("summary", "")
    review.setdefault("drivers", [])
    review.setdefault("monitor", [])
    review.setdefault("outlook", "")
    for field in ("summary", "outlook"):
        if review.get(field) in _LEGACY_PREVIEW_PLACEHOLDERS:
            review[field] = ""
    for field in ("drivers", "monitor", "blocks"):
        if field in review and not isinstance(review[field], list):
            review[field] = []

    history = sections.get("historical_performance")
    if not isinstance(history, dict):
        history = {}
        sections["historical_performance"] = history
    if not isinstance(history.get("rows"), list):
        history["rows"] = []

    if not isinstance(sections.get("company_news"), list):
        sections["company_news"] = []
    if not isinstance(sections.get("constituents"), list):
        sections["constituents"] = []

    analytics = sections.get("analytics")
    if not isinstance(analytics, dict):
        analytics = {}
        sections["analytics"] = analytics
    for field in ("top10", "sectors", "top", "bottom", "portfolio"):
        if not isinstance(analytics.get(field), list):
            analytics[field] = []

    if not isinstance(sections.get("footnotes"), dict):
        sections["footnotes"] = {}
    return result


def _merge_tokens(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_tokens(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=8)
def _render_tokens(version: str) -> dict[str, Any]:
    token_path = ROOT / "tokens" / f"{Path(version).name}.json"
    if not token_path.is_file():
        token_path = ROOT / "tokens" / "3033-v1.json"
    tokens = json.loads(token_path.read_text(encoding="utf-8"))
    parent = tokens.get("extends")
    return _merge_tokens(_render_tokens(str(parent)), tokens) if parent else tokens


@lru_cache(maxsize=2)
def _embedded_cjk_font_css(language_mode: str = ZH_HANS) -> str:
    """Embed the target-script Noto face so HTML and PDF use the same CJK glyph forms."""
    traditional = is_zh_hant(language_mode)
    family = "Embedded Noto Sans CJK TC" if traditional else "Embedded Noto Sans CJK SC"
    windows_font = "NotoSansTC-VF.ttf" if traditional else "NotoSansSC-VF.ttf"
    candidates = (
        # Developer/CI Windows image.  This variable font covers regular through bold.
        (Path("C:/Windows/Fonts") / windows_font, None),
        # Debian's fonts-noto-cjk package, installed by backend/Dockerfile.
        (
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        ),
        (
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
        ),
    )
    for regular_path, bold_path in candidates:
        if not regular_path.is_file():
            continue
        regular = base64.b64encode(regular_path.read_bytes()).decode("ascii")
        regular_format = "truetype" if regular_path.suffix.lower() == ".ttf" else "collection"
        if bold_path is None:
            return (
                f'@font-face{{font-family:"{family}";'
                f'src:url("data:font/ttf;base64,{regular}") format("{regular_format}");'
                'font-style:normal;font-weight:100 900;font-display:block;}'
            )
        if not bold_path.is_file():
            continue
        bold = base64.b64encode(bold_path.read_bytes()).decode("ascii")
        return (
            f'@font-face{{font-family:"{family}";'
            f'src:url("data:font/collection;base64,{regular}") format("{regular_format}");'
            'font-style:normal;font-weight:400;font-display:block;}'
            f'@font-face{{font-family:"{family}";'
            f'src:url("data:font/collection;base64,{bold}") format("{regular_format}");'
            'font-style:normal;font-weight:700;font-display:block;}'
        )
    return ""


# The lane mark is a control, not decoration, so it must survive a token file that forgets it.
# The tokens decide how it looks; this decides that it exists at all.
_TESTING_BANNER_FALLBACK = {
    "label": "TESTING DATA - NOT FOR DISTRIBUTION",
    "watermark": "TESTING",
    "color": "#c45f5f",
    "opacity": 0.12,
    "watermarkPt": 84,
    "chipPt": 7,
    "rotationDeg": -28,
}


def testing_banner(document: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the TESTING-lane mark for a document, or ``None`` on the production lane.

    Resolved here rather than at each call site so HTML, PDF and DOCX take the same wording and
    colour from the same versioned place, and so no format can quietly omit it.
    """
    if str(document.get("lane", "PRODUCTION")) != "TESTING":
        return None
    tokens = _render_tokens(str(document.get("design_token_version", "3033-v1")))
    return {**_TESTING_BANNER_FALLBACK, **(tokens.get("testingBanner") or {})}


def _polar_point(center: float, radius: float, angle: float) -> tuple[float, float]:
    radians = math.radians(angle - 90)
    return center + radius * math.cos(radians), center + radius * math.sin(radians)


def _donut_path(center: float, outer_radius: float, inner_radius: float, start: float, end: float) -> str:
    sweep = end - start
    outer_start = _polar_point(center, outer_radius, start)
    outer_end = _polar_point(center, outer_radius, end)
    inner_end = _polar_point(center, inner_radius, end)
    inner_start = _polar_point(center, inner_radius, start)
    large_arc = 1 if sweep > 180 else 0
    return (
        f"M {outer_start[0]:.4f} {outer_start[1]:.4f} "
        f"A {outer_radius:.4f} {outer_radius:.4f} 0 {large_arc} 1 {outer_end[0]:.4f} {outer_end[1]:.4f} "
        f"L {inner_end[0]:.4f} {inner_end[1]:.4f} "
        f"A {inner_radius:.4f} {inner_radius:.4f} 0 {large_arc} 0 {inner_start[0]:.4f} {inner_start[1]:.4f} Z"
    )


def sector_chart(
    chart_snapshot: dict[str, Any] | None,
    chart_tokens: dict[str, Any],
    language_mode: str = "EN",
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Lay out the `industry_breakdown` chart snapshot.

    Ordering, the zero-weight filter, the display string and the colour token are all decided
    in ``domain.metrics.industry_breakdown.sector_chart_snapshot``. Everything here is geometry and colour
    resolution — the renderer must not regroup, re-sort or recompute (rules document §4.3).
    """
    series = (chart_snapshot or {}).get("series") or []
    if not series:
        return {"has_data": False, "rows": []}

    view_box = float(chart_tokens["viewBoxSize"])
    center = view_box / 2
    outer_radius = float(chart_tokens["outerRadius"])
    inner_radius = float(chart_tokens["innerRadius"])
    label_radius = float(chart_tokens["labelOutsideRadius"])
    inside_threshold = float(chart_tokens["labelInsideThresholdRatio"])
    palette = [str(color) for color in chart_tokens["palette"]]
    color_tokens = {str(key): str(value) for key, value in (chart_tokens.get("colorTokens") or {}).items()}

    rows: list[dict[str, Any]] = []
    outside: list[dict[str, Any]] = []
    for row in series:
        start = float(row.get("start_angle") or 0)
        end = float(row.get("end_angle") or 0)
        order = int(row.get("sort_order") or len(rows) + 1)
        token = str(row.get("color_token") or "")
        middle = (start + end) / 2
        if is_zh_hans(language_mode):
            sector_name = str(row.get("label_zh_hans") or "")
            if not sector_name and row.get("label_zh_hant"):
                sector_name = traditional_to_simplified(row.get("label_zh_hant"))
        elif is_zh_hant(language_mode):
            sector_name = str(row.get("label_zh_hant") or "")
            if not sector_name and row.get("label_zh_hans"):
                sector_name = simplified_to_traditional(row.get("label_zh_hans"))
        else:
            sector_name = str(row.get("label") or "")
        sector_name = str((overrides or {}).get(str(row.get("code") or "")) or sector_name)
        chart_row = {
            "sector": sector_name,
            "display_value": str(row.get("display_value") or ""),
            "color": color_tokens.get(token, palette[(order - 1) % len(palette)]),
            "path": _donut_path(center, outer_radius, inner_radius, start, end),
            "inside": (end - start) / 360 >= inside_threshold,
        }
        if chart_row["inside"]:
            x, y = _polar_point(center, (outer_radius + inner_radius) / 2, middle)
            chart_row["label_x"], chart_row["label_y"] = round(x, 3), round(y, 3)
            chart_row["label_anchor"] = "middle"
        else:
            outside.append(chart_row)
            chart_row["_middle"] = middle
        rows.append(chart_row)

    # Slivers get a leader line into the empty corner beside the ring. Sides alternate so two
    # adjacent slivers — the 1.7% and 1.3% industries in the reference — do not collide, and the
    # text grows outward from `label_radius`, which is chosen to keep it inside the view box.
    for index, chart_row in enumerate(outside):
        side = -1 if index % 2 == 0 else 1
        anchor_x, anchor_y = _polar_point(center, outer_radius + 1, chart_row.pop("_middle"))
        elbow_x, elbow_y = anchor_x + side * 4, anchor_y - 5
        text_x = center + side * label_radius
        chart_row["leader"] = (
            f"{anchor_x:.3f},{anchor_y:.3f} {elbow_x:.3f},{elbow_y:.3f} "
            f"{text_x - side * 2:.3f},{elbow_y:.3f}"
        )
        chart_row["label_x"], chart_row["label_y"] = round(text_x, 3), round(elbow_y + 1.4, 3)
        chart_row["label_anchor"] = "end" if side < 0 else "start"

    localized_summary = ", ".join(
        f"{item['sector']} {item['display_value']}" for item in rows
    )
    return {
        "has_data": True,
        "view_box": view_box,
        "box_mm": float(chart_tokens["boxWidthMm"]),
        "rows": rows,
        "alt_text": (
            f"{term('sector_breakdown', language_mode).rstrip('*')}：{localized_summary}"
            if is_chinese(language_mode)
            else str((chart_snapshot or {}).get("alt_text") or "")
        ),
    }


def localized_document(document: dict[str, Any], language_mode: str) -> dict[str, Any]:
    result = deepcopy(document)
    overrides = result.get("terminology_overrides") or {}
    securities = overrides.get("securities") or {}
    industries = overrides.get("industries") or {}
    sections = result.get("sections") or {}
    for row in sections.get("constituents") or []:
        name, source = localized_row_name(row, language_mode)
        row["display_name"] = str(securities.get(str(row.get("security_code") or "")) or name)
        row["display_name_source"] = "MANUAL_OVERRIDE" if securities.get(str(row.get("security_code") or "")) else source
    analytics = sections.get("analytics") or {}
    for key in ("top10", "top", "bottom"):
        for row in analytics.get(key) or []:
            name, source = localized_row_name(row, language_mode)
            row["display_issuer"] = str(securities.get(str(row.get("security_code") or "")) or name)
            row["display_name_source"] = "MANUAL_OVERRIDE" if securities.get(str(row.get("security_code") or "")) else source
    for row in analytics.get("portfolio") or []:
        if is_chinese(language_mode):
            row["label"] = localized_portfolio_label(
                row.get("metric_code"), row.get("label", ""), language_mode
            )
            if row.get("display_value") == "N/A":
                row["display_value"] = term("no_data", language_mode)
                row["value"] = term("no_data", language_mode)
            else:
                row["display_value"] = localized_portfolio_value(row.get("display_value"), language_mode)
                row["value"] = row["display_value"]
    result["month_name"] = month_name(date.fromisoformat(str(result.get("report_date"))), language_mode)
    result["_industry_overrides"] = industries
    return result


def render_html(
    report: Report,
    document: dict[str, Any],
    *,
    preview: bool = False,
    layout_mode: Literal["continuous", "paged"] = "continuous",
) -> str:
    if preview:
        document = _preview_document(report, document)
    language_mode = str(document.get("language_mode") or report.language_mode or "EN")
    document = localized_document(document, language_mode)
    logo = base64.b64encode((ROOT / "static" / "csop-logo.png").read_bytes()).decode("ascii")
    template_version = str(document.get("template_version", "3033-v1"))
    design_token_version = str(document.get("design_token_version", "3033-v1"))
    tokens = _render_tokens(design_token_version)
    sections = document["sections"]
    banner = testing_banner(document)
    if banner and is_chinese(language_mode):
        banner = {**banner, "label": term("testing_label", language_mode), "watermark": term("testing_watermark", language_mode)}
    portfolio = normalize_portfolio_rows(sections.get("analytics", {}).get("portfolio"), "HKD")
    if is_chinese(language_mode):
        for row in portfolio:
            row["label"] = localized_portfolio_label(
                row.get("metric_code"), row.get("label", ""), language_mode
            )
            if row.get("display_value") == "N/A":
                row["display_value"] = term("no_data", language_mode)
            else:
                row["display_value"] = localized_portfolio_value(row.get("display_value"), language_mode)
    return env.get_template("3033.html.j2").render(
        report=report,
        doc=document,
        sections=sections,
        language_mode=language_mode,
        html_language="zh-CN" if is_zh_hans(language_mode) else "zh-HK" if is_zh_hant(language_mode) else "en",
        cjk_font_css=_embedded_cjk_font_css(language_mode) if is_chinese(language_mode) else "",
        layout_mode=layout_mode,
        t=lambda key, **values: term(key, language_mode, **values),
        product_display_name=(document.get("terminology_overrides") or {}).get("product_name") or report.product_name,
        benchmark_display_name=(document.get("terminology_overrides") or {}).get("benchmark_name") or document.get("benchmark_name") or report.benchmark_code,
        report_date_long=long_date(report.report_date, language_mode),
        logo_data=logo,
        review_title=review_display_title(document),
        enable_review_layout=template_version != "3033-v1",
        testing_banner=banner,
        portfolio_analysis=portfolio,
        sector_chart=sector_chart(
            sections.get("analytics", {}).get("sector_chart"),
            tokens["chart"]["sectorDonut"],
            language_mode,
            document.get("_industry_overrides") or {},
        ),
    )
