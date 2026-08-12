"""Calculation orchestration.

The arithmetic itself lives in ``domain.calculation`` and stays pure. This module supplies the
session-bound half: it reads the active snapshot, hands a derived payload to the pure layer, and
persists the resulting ``MetricValue`` / ``ModuleSnapshot`` / ``QualityCheckResult`` rows with
their lineage.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..calculation import build_lineage_footnotes, calculate_snapshot, historical_performance, snapshot_checks
from ..document import bind_snapshot, checksum
from ..models import (
    DataSnapshot,
    MetricValue,
    ModuleSnapshot,
    QualityCheckResult,
    Report,
    ReportDocument,
    ReportStatus,
)
from .audit import audit
from .catalog import resolve_product
from .documents import latest_document
from .snapshots import ensure_snapshot_datasets, require_complete_snapshot


def persist_calculation_records(
    db: Session,
    report: Report,
    snapshot: DataSnapshot,
    formula_version: str,
    derived_payload: dict,
    metrics: dict,
    results: list[dict],
) -> dict[str, ModuleSnapshot]:
    datasets = ensure_snapshot_datasets(db, snapshot)
    datasets_by_type = {item.dataset_type: item for item in datasets}

    def dataset_ids_for(dataset_types: tuple[str, ...]) -> list[str]:
        return sorted(
            datasets_by_type[dataset_type].id
            for dataset_type in dataset_types
            if dataset_type in datasets_by_type
        )

    metric_rows: list[MetricValue] = []
    metric_specs: list[dict] = []

    def add_metric(
        metric_code: str,
        raw,
        unit: str,
        dimension_key: str = "",
        period_start=None,
        period_end=None,
        lineage: dict | None = None,
        dataset_types: tuple[str, ...] = (),
    ) -> None:
        if raw is None:
            return
        metric_specs.append({
            "metric_code": metric_code,
            "raw": raw,
            "unit": unit,
            "dimension_key": dimension_key,
            "period_start": period_start,
            "period_end": period_end,
            "lineage": lineage or {},
            "dataset_types": dataset_types,
        })

    summary_units = {
        "constituent_count": "COUNT",
        "weight_total": "RATIO",
        "sector_count": "COUNT",
        "turnover_observation_count": "COUNT",
        "turnover_expected_day_count": "COUNT",
        "turnover_average": "AMOUNT",
        "turnover_coverage": "RATIO",
        "aum_value": "AMOUNT",
        "top_security_code": "SECURITY_CODE",
        "bottom_security_code": "SECURITY_CODE",
    }
    summary_dependencies = {
        "constituent_count": ("constituent_snapshot",),
        "weight_total": ("constituent_snapshot",),
        "sector_count": ("constituent_snapshot", "industry_master"),
        "top_security_code": ("constituent_snapshot", "constituent_period_return"),
        "bottom_security_code": ("constituent_snapshot", "constituent_period_return"),
        "turnover_observation_count": ("fund_kpi_daily", "trading_calendar"),
        "turnover_expected_day_count": ("trading_calendar",),
        "turnover_average": ("fund_kpi_daily", "trading_calendar"),
        "turnover_coverage": ("fund_kpi_daily", "trading_calendar"),
        "aum_value": ("fund_kpi_daily",),
        "next_rebalancing_date": ("index_event",),
    }
    for metric_code, raw in metrics.items():
        add_metric(
            metric_code,
            raw,
            summary_units.get(metric_code, "TEXT"),
            dataset_types=summary_dependencies.get(metric_code, ()),
        )

    history = derived_payload.get("historical_performance", {})
    periods = history.get("periods", {})
    for row in history.get("rows", []):
        dimension = str(row.get("role") or row.get("name") or "")
        for field in ("return_1m", "return_3m", "return_6m", "return_ytd"):
            period = periods.get(field, {})
            add_metric(
                f"historical.{field}",
                row.get(field),
                "RATIO",
                dimension,
                date.fromisoformat(period["period_start"]) if period.get("period_start") else None,
                date.fromisoformat(period["period_end"]) if period.get("period_end") else None,
                {"instrument": row.get("name"), "role": row.get("role")},
                ("total_return_series",),
            )

    return_periods = derived_payload.get("return_periods", {})
    constituent_starts = return_periods.get("starts", {})
    constituent_end = return_periods.get("end")
    for row in derived_payload.get("constituents", []):
        dimension = str(row.get("security_code") or "")
        add_metric(
            "constituent.close_price", row.get("close_price"),
            str(row.get("currency") or "UNKNOWN"), dimension,
            dataset_types=("constituent_snapshot",),
        )
        add_metric(
            "constituent.weight", row.get("weight"), "RATIO", dimension,
            dataset_types=("constituent_snapshot",),
        )
        for field in ("return_1m", "return_3m", "return_6m", "return_ytd"):
            add_metric(
                f"constituent.{field}",
                row.get(field),
                "RATIO",
                dimension,
                date.fromisoformat(constituent_starts[field]) if constituent_starts.get(field) else None,
                date.fromisoformat(constituent_end) if constituent_end else None,
                {"missing_reason": row.get(f"{field}_missing_reason")},
                ("constituent_period_return",),
            )

    for row in derived_payload.get("analytics", {}).get("sectors", []):
        add_metric(
            "industry.weight",
            row.get("weight"),
            "RATIO",
            str(row.get("code") or row.get("sector") or ""),
            lineage={"label": row.get("sector"), "taxonomy": row.get("taxonomy")},
            dataset_types=("constituent_snapshot", "industry_master"),
        )

    for spec in metric_specs:
        metric_code = spec["metric_code"]
        raw = spec["raw"]
        dimension_key = spec["dimension_key"]
        metric_dataset_ids = dataset_ids_for(spec["dataset_types"])
        existing = db.scalar(select(MetricValue).where(
            MetricValue.snapshot_id == snapshot.id,
            MetricValue.metric_code == metric_code,
            MetricValue.dimension_key == dimension_key,
            MetricValue.formula_version == formula_version,
        ))
        if existing:
            metric_rows.append(existing)
            continue
        unit = spec["unit"]
        try:
            numeric = Decimal(str(raw)) if unit not in {"TEXT", "SECURITY_CODE"} and raw is not None and not isinstance(raw, bool) else None
        except InvalidOperation:
            numeric = None
        item = MetricValue(
            snapshot_id=snapshot.id,
            metric_code=metric_code,
            dimension_key=dimension_key,
            value=numeric,
            raw_value="" if raw is None else str(raw),
            unit=unit,
            period_start=spec["period_start"],
            period_end=spec["period_end"],
            formula_version=formula_version,
            lineage={
                "source_system": snapshot.source_policy,
                "snapshot_id": snapshot.id,
                "snapshot_dataset_ids": metric_dataset_ids,
                "snapshot_dataset_types": list(spec["dataset_types"]),
                "formula_version": formula_version,
                "input_checksum": snapshot.checksum,
                **spec["lineage"],
            },
        )
        db.add(item)
        metric_rows.append(item)
    db.flush()

    for result in results:
        entity_id = str(result.get("entity_id") or "")
        result_key = f"{result['check_id']}:{entity_id}"
        if db.scalar(select(QualityCheckResult).where(
            QualityCheckResult.snapshot_id == snapshot.id,
            QualityCheckResult.result_key == result_key,
        )):
            continue
        db.add(QualityCheckResult(
            snapshot_id=snapshot.id,
            result_key=result_key,
            check_id=result["check_id"],
            severity=result["severity"],
            status=result["status"],
            entity_id=entity_id or None,
            actual=result.get("actual"),
            threshold=result.get("threshold"),
            fix_hint=result.get("fix_hint", ""),
        ))

    module_payloads = {
        "historical_performance": derived_payload.get("historical_performance", {"rows": []}),
        "constituents_performance": {
            "rows": derived_payload.get("constituents", []),
            "next_rebalancing_date": derived_payload.get("next_rebalancing_date"),
        },
        "final_analytics": derived_payload.get("analytics", {}),
        "footnotes": derived_payload.get("footnotes", {}),
    }
    modules: dict[str, ModuleSnapshot] = {}
    module_metric_prefixes = {
        "historical_performance": ("historical.",),
        "constituents_performance": ("constituent.",),
        "final_analytics": (
            "constituent.weight", "constituent.return_1m", "industry.", "aum_", "turnover_",
            "constituent_count", "weight_total", "sector_count", "top_security_code", "bottom_security_code",
        ),
        "footnotes": (),
    }
    module_dataset_types = {
        "historical_performance": ("total_return_series",),
        "constituents_performance": ("constituent_snapshot", "constituent_period_return", "index_event"),
        "final_analytics": (
            "constituent_snapshot", "constituent_period_return", "industry_master",
            "fund_kpi_daily", "trading_calendar",
        ),
        "footnotes": tuple(sorted(datasets_by_type)),
    }
    for module_code, payload in module_payloads.items():
        existing = db.scalar(select(ModuleSnapshot).where(
            ModuleSnapshot.snapshot_id == snapshot.id,
            ModuleSnapshot.module_code == module_code,
            ModuleSnapshot.formula_version == formula_version,
            ModuleSnapshot.template_version == report.template_version,
        ))
        if existing:
            modules[module_code] = existing
            continue
        prefixes = module_metric_prefixes[module_code]
        metric_ids = sorted(
            item.id for item in metric_rows
            if prefixes and any(item.metric_code.startswith(prefix) for prefix in prefixes)
        )
        source_dataset_ids = dataset_ids_for(module_dataset_types[module_code])
        item = ModuleSnapshot(
            snapshot_id=snapshot.id,
            module_code=module_code,
            formula_version=formula_version,
            template_version=report.template_version,
            source_dataset_ids=source_dataset_ids,
            metric_value_ids=metric_ids,
            payload=payload,
            display_format={},
            footnote_bindings=list((derived_payload.get("footnotes") or {}).keys()),
            checksum=checksum(payload),
            input_checksum=checksum({
                "source_datasets": [
                    {
                        "id": item_id,
                        "checksum": next(dataset.checksum for dataset in datasets if dataset.id == item_id),
                    }
                    for item_id in source_dataset_ids
                ],
                "formula_version": formula_version,
                "module_code": module_code,
            }),
        )
        db.add(item)
        modules[module_code] = item
    db.flush()
    return modules


def run_calculation(db: Session, report: Report, request_id: str) -> tuple[dict, ReportDocument, list[dict]]:
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    if not report.active_snapshot_id:
        raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED"})
    snapshot = db.get(DataSnapshot, report.active_snapshot_id)
    require_complete_snapshot(snapshot)
    product = resolve_product(db, report.product_code, report.report_date)
    formula_version = product.formula_profile
    derived_payload = json.loads(json.dumps(snapshot.payload))
    if derived_payload.get("total_return_series"):
        try:
            derived_payload["historical_performance"] = historical_performance(
                derived_payload["total_return_series"],
                report.report_date,
                formula_version,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail={
                "error_code": "HISTORICAL_PERIODS_INCOMPLETE",
                "message": str(error),
                "severity": "BLOCKING",
                "fix_hint": "Upload enough common FUND and BENCHMARK Total Return dates for every required period.",
            }) from error
    # Lineage the pure calculation layer cannot look up for itself. Seeding it here lets the
    # chart snapshot carry the §4.3 traceability fields without giving calculation.py a session.
    derived_payload["snapshot_id"] = snapshot.id
    derived_payload["mapping_version"] = snapshot.mapping_version
    derived_payload["formula_version"] = formula_version
    derived_payload["snapshot_dataset_ids"] = {
        item.dataset_type: item.id for item in ensure_snapshot_datasets(db, snapshot)
    }
    analytics, metrics = calculate_snapshot(derived_payload)
    if metrics.get("next_rebalancing_date"):
        derived_payload["next_rebalancing_date"] = metrics["next_rebalancing_date"]
    derived_payload.update({"analytics": analytics, "metrics": metrics, "formula_version": formula_version})
    derived_payload["footnotes"] = build_lineage_footnotes(derived_payload, metrics)
    results = snapshot_checks(derived_payload, product.expected_constituent_count)
    modules = persist_calculation_records(
        db,
        report,
        snapshot,
        formula_version,
        derived_payload,
        metrics,
        results,
    )
    current = latest_document(db, report.id)
    content = bind_snapshot(current.content, derived_payload, lane=snapshot.lane)
    content["formula_version"] = formula_version
    content["module_bindings"] = {
        module_code: {"module_snapshot_id": item.id, "checksum": item.checksum}
        for module_code, item in modules.items()
    }
    document = ReportDocument(
        report_id=report.id, version=current.version + 1, snapshot_id=snapshot.id,
        template_version=report.template_version, language_mode=report.language_mode,
        content=content, checksum=checksum(content),
    )
    db.add(document); report.version += 1
    blocking = [item for item in results if item["severity"] == "BLOCKING" and item["status"] != "PASSED"]
    report.status = ReportStatus.QA_BLOCKED if blocking else ReportStatus.EDITING
    audit(db, "calculation.completed", "report", report.id, request_id, {"formula_version": formula_version, "metrics": metrics})
    db.commit(); db.refresh(document)
    return metrics, document, results
