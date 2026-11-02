"""Shared, render-only report heading resolution for every output format."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from app.domain.localization import term


@dataclass(frozen=True)
class ReportHeading:
    product: str
    commentary: str

    @property
    def flat(self) -> str:
        return f"{self.product} {self.commentary}"


def resolve_report_heading(report: Any, content: Mapping[str, Any]) -> ReportHeading:
    """Return the two visual title lines without mutating the finalized document."""

    language_mode = str(content.get("language_mode") or report.language_mode or "EN")
    terminology_value = content.get("terminology_overrides")
    terminology = terminology_value if isinstance(terminology_value, Mapping) else {}
    product = str(terminology.get("product_name") or report.product_name).strip()
    ticker = str(content.get("product_ticker") or f"{report.product_code}.HK").strip().strip("()")
    ticker_key = re.sub(r"[^a-z0-9]", "", ticker.casefold())
    product_key = re.sub(r"[^a-z0-9]", "", product.casefold())
    if ticker and ticker_key not in product_key:
        product = f"{product} ({ticker})"
    return ReportHeading(
        product=product,
        commentary=term("monthly_commentary", language_mode),
    )
