from __future__ import annotations

from datetime import date
from typing import Any

from app.integrations.da_report import DaReportProviderError, load_monthly_data

from .models import ProductCatalog


def compose_da_report_fragment(product: ProductCatalog, report_date: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bindings = {
        "fund_total_return_instrument_code": product.fund_total_return_instrument_code,
        "benchmark_instrument_code": product.benchmark_instrument_code,
        "fund_kpi_product_code": product.fund_kpi_product_code,
        "trading_calendar_code": product.trading_calendar_code,
        "constituent_index_code": product.constituent_index_code,
    }
    missing = sorted(key for key, value in bindings.items() if not value)
    if missing:
        return {}, [{
            "check_id": "PRODUCT_AUTO_DATA_BINDING_MISSING",
            "error_code": "PRODUCT_AUTO_DATA_BINDING_MISSING",
            "severity": "BLOCKING",
            "status": "FAILED",
            "message": f"The product is missing automatic data bindings: {', '.join(missing)}.",
            "actual": {"missing": missing},
            "threshold": {"required": sorted(bindings)},
            "fix_hint": "Import a new effective ProductCatalog version with every DA-Report binding populated.",
        }]
    try:
        fragment = load_monthly_data(
            product_code=str(product.fund_kpi_product_code),
            fund_instrument_code=str(product.fund_total_return_instrument_code),
            benchmark_instrument_code=product.benchmark_instrument_code,
            trading_calendar_code=str(product.trading_calendar_code),
            constituent_index_code=product.constituent_index_code,
            report_date=report_date,
        )
    except DaReportProviderError as error:
        return {}, [{
            "check_id": error.code,
            "error_code": error.code,
            "severity": "BLOCKING",
            "status": "FAILED",
            "message": error.message,
            "actual": None,
            "threshold": "A complete read-only DA-Report monthly-data snapshot",
            "fix_hint": "Refresh the approved DA-Report SQLite snapshot, then retry automatic data refresh.",
        }]
    return fragment, []