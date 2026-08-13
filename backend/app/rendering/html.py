from __future__ import annotations

import base64
import json
import math
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.domain.document import review_display_title
from app.domain.models import Report

ROOT = Path(__file__).resolve().parent
env = Environment(
    loader=FileSystemLoader(ROOT / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=StrictUndefined,
)


def pct(value: Decimal | float | int | str | None) -> str:
    return "N/A" if value is None else f"{Decimal(str(value)) * Decimal('100'):.2f}"


def price(value: Decimal | float | int | str | None) -> str:
    if value is None:
        return "N/A"
    return f"{Decimal(str(value)):.2f}".rstrip("0").rstrip(".")


def long_date(value: date) -> str:
    return value.strftime("%B %d, %Y").replace(" 0", " ")


env.filters.update(pct=pct, price=price)


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


def sector_chart(chart_snapshot: dict[str, Any] | None, chart_tokens: dict[str, Any]) -> dict[str, Any]:
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
        chart_row = {
            "sector": str(row.get("label") or ""),
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

    return {
        "has_data": True,
        "view_box": view_box,
        "box_mm": float(chart_tokens["boxWidthMm"]),
        "rows": rows,
        "alt_text": str((chart_snapshot or {}).get("alt_text") or ""),
    }


def render_html(report: Report, document: dict[str, Any]) -> str:
    logo = base64.b64encode((ROOT / "static" / "csop-logo.png").read_bytes()).decode("ascii")
    template_version = str(document.get("template_version", "3033-v1"))
    design_token_version = str(document.get("design_token_version", "3033-v1"))
    tokens = _render_tokens(design_token_version)
    sections = document["sections"]
    return env.get_template("3033.html.j2").render(
        report=report,
        doc=document,
        sections=sections,
        report_date_long=long_date(report.report_date),
        logo_data=logo,
        review_title=review_display_title(document),
        enable_review_layout=template_version != "3033-v1",
        testing_banner=testing_banner(document),
        sector_chart=sector_chart(
            sections.get("analytics", {}).get("sector_chart"),
            tokens["chart"]["sectorDonut"],
        ),
    )
