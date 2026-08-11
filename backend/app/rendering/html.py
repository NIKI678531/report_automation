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
    legacy_sectors: list[dict[str, Any]] | None,
    chart_tokens: dict[str, Any],
) -> dict[str, Any]:
    rows = []
    for row in (chart_snapshot or {}).get("slices", []):
        weight = float(row.get("weight") or 0)
        if weight > 0:
            rows.append({
                "sector": str(row.get("label") or ""),
                "weight": weight,
                "start_angle": float(row.get("start_angle") or 0),
                "end_angle": float(row.get("end_angle") or 0),
                "color_index": int(row.get("color_index") or 0),
            })
    if not rows:
        cursor = 0.0
        total_legacy = sum(float(row.get("weight") or 0) for row in legacy_sectors or [])
        for index, row in enumerate(legacy_sectors or []):
            weight = float(row.get("weight") or 0)
            if weight <= 0 or total_legacy <= 0:
                continue
            start = cursor
            cursor += weight / total_legacy * 360
            rows.append({
                "sector": str(row.get("sector") or ""),
                "weight": weight,
                "start_angle": start,
                "end_angle": cursor,
                "color_index": index,
            })
    total = sum(row["weight"] for row in rows)
    if total <= 0:
        return {"has_data": False, "rows": []}

    view_box = float(chart_tokens["viewBoxSize"])
    center = view_box / 2
    outer_radius = float(chart_tokens["outerRadius"])
    inner_radius = float(chart_tokens["innerRadius"])
    palette = [str(color) for color in chart_tokens["palette"]]
    chart_rows: list[dict[str, Any]] = []
    for row in rows:
        color = palette[row["color_index"] % len(palette)]
        chart_rows.append({
            **row,
            "color": color,
            "path": _donut_path(center, outer_radius, inner_radius, row["start_angle"], row["end_angle"]),
        })
    summary = ", ".join(f"{row['sector']} {row['weight'] / total:.1%}" for row in chart_rows)
    return {
        "has_data": True,
        "view_box": view_box,
        "rows": chart_rows,
        "alt_text": f"Index sector breakdown: {summary}",
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
        sector_chart=sector_chart(
            sections.get("analytics", {}).get("sector_chart"),
            sections.get("analytics", {}).get("sectors", []),
            tokens["chart"]["sectorDonut"],
        ),
    )
