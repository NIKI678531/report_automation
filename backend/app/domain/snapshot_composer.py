from __future__ import annotations

from datetime import date
from typing import Any

from app.core.config import settings
from app.integrations.datawarehouse import (
    DataWarehouseProviderError,
    load_historical_performance,
    load_index_constituents,
)
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
    required_series_bindings = ("fund_total_return_instrument_code", "benchmark_instrument_code")
    missing = sorted(key for key in required_series_bindings if not bindings[key])
    findings: list[dict[str, Any]] = []
    if missing:
        return {}, [{
            "check_id": "PRODUCT_AUTO_DATA_BINDING_MISSING",
            "error_code": "PRODUCT_AUTO_DATA_BINDING_MISSING",
            "severity": "BLOCKING",
            "status": "FAILED",
            "message": f"The product is missing automatic data bindings: {', '.join(missing)}.",
            "actual": {"missing": missing},
            "threshold": {"required": sorted(required_series_bindings)},
            "fix_hint": "Import a new effective ProductCatalog version with both official Total Return bindings populated.",
        }]
    optional_missing = sorted(key for key, value in bindings.items() if key not in required_series_bindings and not value)
    if optional_missing:
        findings.append({
            "check_id": "PRODUCT_SUPPORTING_DATA_BINDING_MISSING",
            "error_code": "PRODUCT_SUPPORTING_DATA_BINDING_MISSING",
            "severity": "BLOCKING",
            "status": "FAILED",
            "message": f"The product is missing supporting automatic-data bindings: {', '.join(optional_missing)}.",
            "actual": {"missing": optional_missing},
            "threshold": {"required": sorted(bindings)},
            "fix_hint": "Add the missing ProductCatalog bindings; official Historical Performance can still be displayed.",
        })
    fragment: dict[str, Any] = {"datasets": {}}
    try:
        da_report_fragment = load_monthly_data(
            product_code=str(product.fund_kpi_product_code or ""),
            fund_instrument_code=str(product.fund_total_return_instrument_code),
            benchmark_instrument_code=product.benchmark_instrument_code,
            trading_calendar_code=str(product.trading_calendar_code or ""),
            constituent_index_code=product.constituent_index_code,
            report_date=report_date,
        )
    except DaReportProviderError as error:
        findings.append({
            "check_id": error.code,
            "error_code": error.code,
            "severity": "BLOCKING",
            "status": "FAILED",
            "message": error.message,
            "actual": None,
            "threshold": "A complete read-only DA-Report monthly-data snapshot",
            "fix_hint": "Refresh the approved DA-Report SQLite snapshot, then retry automatic data refresh.",
        })
    else:
        findings.extend(da_report_fragment.pop("_findings", []))
        fragment.update(da_report_fragment)

    if settings.datawarehouse_performance_enabled:
        performance_fragment: dict[str, Any] | None = None
        try:
            performance_fragment = load_historical_performance(
                fund_ticker=product.ticker,
                benchmark_instrument_code=product.benchmark_instrument_code,
                report_date=report_date,
                formula_version=product.formula_profile,
            )
        except DataWarehouseProviderError as error:
            # When the data-warehouse route is enabled it is authoritative for Page 02. Do not
            # silently fall back to the legacy DA-Report Total Return contract.
            fragment.pop("total_return_series", None)
            if isinstance(fragment.get("datasets"), dict):
                fragment["datasets"].pop("total_return_series", None)
            findings.append({
                "check_id": error.code,
                "error_code": error.code,
                "severity": "BLOCKING",
                "status": "FAILED",
                "message": error.message,
                "actual": None,
                "threshold": "Listed product and benchmark period-return rows through the selected report month",
                "fix_hint": "Verify the configured listed share-class mapping and benchmark rows in the CDB performance views, then refresh.",
            })
        else:
            fragment.pop("total_return_series", None)
            datasets = fragment.setdefault("datasets", {})
            datasets.pop("total_return_series", None)
            datasets.update(performance_fragment["datasets"])
            fragment["historical_performance"] = performance_fragment["historical_performance"]
            fragment["source_checksum"] = performance_fragment["source_checksum"]
        if settings.datawarehouse_constituents_enabled and performance_fragment:
            effective_as_of = date.fromisoformat(
                performance_fragment["historical_performance"]["effective_as_of"]
            )
            try:
                constituent_fragment = load_index_constituents(
                    index_code=product.constituent_index_code,
                    report_date=report_date,
                    effective_as_of=effective_as_of,
                )
            except DataWarehouseProviderError as error:
                findings.append({
                    "check_id": error.code,
                    "error_code": error.code,
                    "severity": "BLOCKING",
                    "status": "FAILED",
                    "message": error.message,
                    "actual": None,
                    "threshold": "A report-month CDB constituent identity snapshot for the configured index",
                    "fix_hint": "Verify the configured CDB constituent view, index code and report-month coverage, then refresh.",
                })
            else:
                findings.extend(constituent_fragment.pop("_findings", []))
                fragment["constituents"] = constituent_fragment["constituents"]
                fragment["constituent_index_code"] = constituent_fragment["constituent_index_code"]
                fragment.setdefault("datasets", {}).update(constituent_fragment["datasets"])
    return fragment, findings
