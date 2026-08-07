from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.domain.models import Report

ROOT = Path(__file__).resolve().parent
env = Environment(
    loader=FileSystemLoader(ROOT / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=StrictUndefined,
)


def pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f}"


def price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def long_date(value: date) -> str:
    return value.strftime("%B %d, %Y").replace(" 0", " ")


env.filters.update(pct=pct, price=price)


def render_html(report: Report, document: dict[str, Any]) -> str:
    logo = base64.b64encode((ROOT / "static" / "csop-logo.png").read_bytes()).decode("ascii")
    template_version = str(document.get("template_version", "3033-v1"))
    review = document["sections"]["month_in_review"]
    review_title = "Review" if template_version != "3033-v1" else str(review.get("title", f"{document.get('month_name', '')} in Review"))
    return env.get_template("3033.html.j2").render(
        report=report,
        doc=document,
        sections=document["sections"],
        report_date_long=long_date(report.report_date),
        logo_data=logo,
        review_title=review_title,
        enable_review_layout=template_version != "3033-v1",
    )
