from __future__ import annotations

from datetime import date
from typing import Any

from app.core.config import settings
from app.integrations.datawarehouse import (
    DataWarehouseProviderError,
    load_fund_aum,
    load_fund_kpis,
    load_historical_performance,
    load_index_constituents,
)
from app.integrations.da_report import DaReportProviderError, load_monthly_data, load_monthly_turnover

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
            "fix_hint": "Check the configured DA-Report source, schema and read permissions, then retry automatic data refresh.",
        })
    else:
        findings.extend(da_report_fragment.pop("_findings", []))
        fragment.update(da_report_fragment)

    if settings.datawarehouse_fund_kpi_view:
        try:
            kpi_fragment = load_fund_kpis(
                product_code=str(product.fund_kpi_product_code or product.product_code),
                trading_calendar_code=str(product.trading_calendar_code or ""),
                report_date=report_date,
            )
        except DataWarehouseProviderError as error:
            # A configured CDB view is authoritative for both logical datasets. Keeping either
            # legacy DA-Report dataset would silently mix sources and hide a broken CDB contract.
            fragment.pop("fund_kpis", None)
            fragment.pop("trading_calendar", None)
            datasets = fragment.setdefault("datasets", {})
            datasets.pop("fund_kpi_daily", None)
            datasets.pop("trading_calendar", None)
            findings.append({
                "check_id": error.code,
                "error_code": error.code,
                "severity": "BLOCKING",
                "status": "FAILED",
                "message": error.message,
                "actual": None,
                "threshold": "A complete approved CDB fund-KPI and trading-calendar view",
                "fix_hint": "Verify the configured CDB fund KPI view, grants, schema and report-month rows, then refresh.",
            })
        else:
            findings.extend(kpi_fragment.pop("_findings", []))
            fragment["fund_kpis"] = kpi_fragment["fund_kpis"]
            fragment["trading_calendar"] = kpi_fragment["trading_calendar"]
            datasets = fragment.setdefault("datasets", {})
            datasets.pop("fund_kpi_daily", None)
            datasets.pop("trading_calendar", None)
            datasets.update(kpi_fragment["datasets"])
    elif settings.datawarehouse_fund_aum_view:
        try:
            aum_fragment = load_fund_aum(
                fund_ticker=product.ticker,
                product_code=str(product.fund_kpi_product_code or product.product_code),
                report_date=report_date,
            )
        except DataWarehouseProviderError as error:
            fragment.pop("fund_kpis", None)
            fragment.pop("trading_calendar", None)
            datasets = fragment.setdefault("datasets", {})
            datasets.pop("fund_kpi_daily", None)
            datasets.pop("trading_calendar", None)
            findings.append({
                "check_id": error.code,
                "error_code": error.code,
                "severity": "BLOCKING",
                "status": "FAILED",
                "message": error.message,
                "actual": None,
                "threshold": "A report-month fund-level AUM observation from the approved CDB valuation view",
                "fix_hint": "Verify the configured CDB fund AUM view, grants, schema and report-month rows, then refresh.",
            })
        else:
            aum_findings = list(aum_fragment.pop("_findings", []))
            # This bridge owns AUM only. Remove legacy KPI/calendar data so an unavailable
            # turnover contract cannot be hidden by silently mixing automatic providers. The
            # separately versioned Bloomberg monthly aggregate is allowed below because it owns
            # only turnover and preserves its own formula inputs and lineage.
            fragment["fund_kpis"] = aum_fragment["fund_kpis"]
            fragment.pop("trading_calendar", None)
            datasets = fragment.setdefault("datasets", {})
            datasets.pop("fund_kpi_daily", None)
            datasets.pop("trading_calendar", None)
            datasets.update(aum_fragment["datasets"])
            try:
                turnover_fragment = load_monthly_turnover(
                    product_ticker=product.ticker,
                    report_date=report_date,
                )
            except DaReportProviderError as error:
                # Missing table/month means the existing AUM-only blocking finding remains the
                # useful operator instruction. Malformed or duplicate source rows are surfaced.
                if error.code not in {
                    "DA_REPORT_MONTHLY_TURNOVER_NOT_AVAILABLE",
                    "DA_REPORT_MONTHLY_TURNOVER_NOT_FOUND",
                }:
                    findings.append({
                        "check_id": error.code,
                        "error_code": error.code,
                        "severity": "BLOCKING",
                        "status": "FAILED",
                        "message": error.message,
                        "actual": None,
                        "threshold": "One valid Bloomberg monthly turnover record for the report month",
                        "fix_hint": "Correct and republish market_monthly_turnovers, then refresh automatic data.",
                    })
            else:
                fragment["fund_turnover_monthly"] = turnover_fragment["fund_turnover_monthly"]
                datasets.update(turnover_fragment["datasets"])
                aum_findings = [
                    item for item in aum_findings
                    if item.get("check_id") != "DATAWAREHOUSE_TURNOVER_VIEW_NOT_CONFIGURED"
                ]
            findings.extend(aum_findings)

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
