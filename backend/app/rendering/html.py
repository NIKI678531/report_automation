from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

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

SECTOR_COLORS = ("#5186bd", "#223a8b", "#00b0f0", "#8064a2")


def sector_chart(sectors: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = []
    for row in sectors or []:
        weight = float(row.get("weight") or 0)
        if weight <= 0:
            continue
        rows.append({"sector": str(row.get("sector") or ""), "weight": weight})
    total = sum(row["weight"] for row in rows)
    if total <= 0:
        return {"has_data": False, "gradient": "", "rows": []}

    cursor = 0.0
    stops: list[str] = []
    chart_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        color = SECTOR_COLORS[index % len(SECTOR_COLORS)]
        start = cursor
        cursor += row["weight"] / total * 100
        end = 100.0 if index == len(rows) - 1 else cursor
        stops.append(f"{color} {start:.4f}% {end:.4f}%")
        chart_rows.append({**row, "color": color})
    return {"has_data": True, "gradient": Markup(f"conic-gradient({','.join(stops)})"), "rows": chart_rows}


def render_html(report: Report, document: dict[str, Any]) -> str:
    logo = base64.b64encode((ROOT / "static" / "csop-logo.png").read_bytes()).decode("ascii")
    template_version = str(document.get("template_version", "3033-v1"))
    sections = document["sections"]
    return env.get_template("3033.html.j2").render(
        report=report,
        doc=document,
        sections=sections,
        report_date_long=long_date(report.report_date),
        logo_data=logo,
        review_title=review_display_title(document),
        enable_review_layout=template_version != "3033-v1",
        sector_chart=sector_chart(sections.get("analytics", {}).get("sectors", [])),
    )
