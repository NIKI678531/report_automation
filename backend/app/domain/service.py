from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from decimal import InvalidOperation
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from . import ingestion
from .calculation import build_lineage_footnotes, calculate_snapshot, quality_checks
from .document import DocumentValidationError, bind_snapshot, checksum, initial_document, validate_document_content
from .models import (
    AuditEvent,
    DataImport,
    DataSnapshot,
    IndustryMasterRecord,
    MetricValue,
    ModuleSnapshot,
    NewsFetchRun,
    NewsItem,
    ProductCatalog,
    QualityCheckResult,
    Report,
    ReportDocument,
    ReportNewsCandidate,
    ReportStatus,
    SnapshotDataset,
    SnapshotStatus,
    utcnow,
)
from .schemas import ReportCreate


_NUMBER_TOKEN = re.compile(r"(?<![\w.])[+-]?\d[\d,]*(?:\.\d+)?%?")


def empty_payload(report_date: date) -> dict:
    return {
        "as_of_date": report_date.isoformat(),
        "constituents": [],
        "historical_performance": {"rows": []},
        "company_news": [],
        "analytics": {"top10": [], "sectors": [], "top": [], "bottom": [], "portfolio": []},
        "footnotes": {},
        "datasets": {},
    }


def _snapshot_dataset_specs(payload: dict) -> list[tuple[str, list | dict]]:
    specs: list[tuple[str, list | dict]] = []
    constituents = payload.get("constituents", [])
    if constituents:
        specs.append(("constituent_snapshot", constituents))
        if any(any(row.get(field) is not None for field in ("return_1m", "return_3m", "return_6m", "return_ytd")) for row in constituents):
            specs.append(("constituent_period_return", constituents))
    if payload.get("total_return_series"):
        specs.append(("total_return_series", payload["total_return_series"]))
    if payload.get("fund_kpis"):
        specs.append(("fund_kpi_daily", payload["fund_kpis"]))
    if payload.get("trading_calendar"):
        specs.append(("trading_calendar", payload["trading_calendar"]))
    if payload.get("index_events"):
        specs.append(("index_event", payload["index_events"]))
    if payload.get("industry_master"):
        specs.append(("industry_master", payload["industry_master"]))
    return specs


def import_industry_master(db: Session, rows: list[dict], request_id: str) -> dict[str, int | str]:
    taxonomy = rows[0]["taxonomy"]
    version = rows[0]["version"]
    valid_from = rows[0]["valid_from"]
    valid_to = rows[0]["valid_to"]
    existing_versions = list(db.scalars(select(IndustryMasterRecord).where(
        IndustryMasterRecord.taxonomy == taxonomy,
        IndustryMasterRecord.version != version,
    )))
    for existing in existing_versions:
        existing_end = existing.valid_to or date.max
        incoming_end = valid_to or date.max
        if valid_from <= existing_end and existing.valid_from <= incoming_end:
            raise HTTPException(status_code=422, detail={
                "error_code": "INDUSTRY_VERSION_OVERLAP",
                "message": f"HSICS version {version} overlaps effective version {existing.version}.",
                "severity": "BLOCKING",
                "fix_hint": "Use non-overlapping valid_from/valid_to ranges for taxonomy versions.",
            })
    created = 0
    unchanged = 0
    for row in rows:
        existing = db.scalar(select(IndustryMasterRecord).where(
            IndustryMasterRecord.taxonomy == row["taxonomy"],
            IndustryMasterRecord.version == row["version"],
            IndustryMasterRecord.level == row["level"],
            IndustryMasterRecord.code == row["code"],
        ))
        if existing:
            if existing.checksum != row["checksum"]:
                raise HTTPException(status_code=409, detail={
                    "error_code": "INDUSTRY_MASTER_IMMUTABLE",
                    "message": f"{row['level']} {row['code']} already exists with different content.",
                    "fix_hint": "Import corrected content under a new taxonomy version.",
                })
            unchanged += 1
            continue
        db.add(IndustryMasterRecord(**row))
        created += 1
    audit(db, "industry_master.imported", "industry_master", version, request_id, {
        "taxonomy": taxonomy, "version": version, "created": created, "unchanged": unchanged,
    })
    db.commit()
    return {"taxonomy": taxonomy, "version": version, "created": created, "unchanged": unchanged}


def ensure_snapshot_datasets(db: Session, snapshot: DataSnapshot) -> list[SnapshotDataset]:
    existing = list(db.scalars(select(SnapshotDataset).where(SnapshotDataset.snapshot_id == snapshot.id)))
    by_type = {item.dataset_type: item for item in existing}
    source_objects = sorted({
        str(item.get("filename") or item.get("import_id"))
        for item in (snapshot.payload or {}).get("datasets", {}).values()
        if isinstance(item, dict) and (item.get("filename") or item.get("import_id"))
    })
    for dataset_type, rows in _snapshot_dataset_specs(snapshot.payload or {}):
        if dataset_type in by_type:
            continue
        row_count = len(rows) if isinstance(rows, list) else len(rows)
        item = SnapshotDataset(
            snapshot_id=snapshot.id,
            dataset_type=dataset_type,
            source_type=snapshot.source_policy,
            source_object=", ".join(source_objects) or snapshot.source_policy,
            row_count=row_count,
            coverage=Decimal("1") if dataset_type == "constituent_snapshot" and snapshot.status == SnapshotStatus.VALID else None,
            checksum=checksum(rows),
            parser_version=None,
            mapping_version=snapshot.mapping_version,
            validation_results=list(snapshot.quality_results or []),
            lineage={
                "source_system": snapshot.source_policy,
                "dataset_type": dataset_type,
                "snapshot_id": snapshot.id,
                "as_of_date": snapshot.as_of_date.isoformat(),
                "mapping_version": snapshot.mapping_version,
                "checksum": checksum(rows),
            },
        )
        db.add(item)
        by_type[dataset_type] = item
    db.flush()
    return list(by_type.values())


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
    dataset_ids = sorted(item.id for item in datasets)
    metric_rows: list[MetricValue] = []
    metric_specs: list[dict] = []

    def add_metric(metric_code: str, raw, unit: str, dimension_key: str = "", period_start=None, period_end=None, lineage: dict | None = None) -> None:
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
    for metric_code, raw in metrics.items():
        add_metric(metric_code, raw, summary_units.get(metric_code, "TEXT"))

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
            )

    for row in derived_payload.get("constituents", []):
        dimension = str(row.get("security_code") or "")
        add_metric("constituent.close_price", row.get("close_price"), str(row.get("currency") or "UNKNOWN"), dimension)
        add_metric("constituent.weight", row.get("weight"), "RATIO", dimension)
        for field in ("return_1m", "return_3m", "return_6m", "return_ytd"):
            period = periods.get(field, {})
            add_metric(
                f"constituent.{field}",
                row.get(field),
                "RATIO",
                dimension,
                date.fromisoformat(period["period_start"]) if period.get("period_start") else None,
                date.fromisoformat(period["period_end"]) if period.get("period_end") else None,
                {"missing_reason": row.get(f"{field}_missing_reason")},
            )

    for row in derived_payload.get("analytics", {}).get("sectors", []):
        add_metric(
            "industry.weight",
            row.get("weight"),
            "RATIO",
            str(row.get("code") or row.get("sector") or ""),
            lineage={"label": row.get("sector"), "taxonomy": row.get("taxonomy")},
        )

    for spec in metric_specs:
        metric_code = spec["metric_code"]
        raw = spec["raw"]
        dimension_key = spec["dimension_key"]
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
                "snapshot_dataset_ids": dataset_ids,
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
        item = ModuleSnapshot(
            snapshot_id=snapshot.id,
            module_code=module_code,
            formula_version=formula_version,
            template_version=report.template_version,
            source_dataset_ids=dataset_ids,
            metric_value_ids=metric_ids,
            payload=payload,
            display_format={},
            footnote_bindings=list((derived_payload.get("footnotes") or {}).keys()),
            checksum=checksum(payload),
            input_checksum=checksum({
                "snapshot_checksum": snapshot.checksum,
                "formula_version": formula_version,
                "module_code": module_code,
            }),
        )
        db.add(item)
        modules[module_code] = item
    db.flush()
    return modules


def _numeric_tokens(value: object) -> set[str]:
    text_value = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return {match.group(0) for match in _NUMBER_TOKEN.finditer(text_value)}


def _numeric_values(tokens: set[str]) -> set[Decimal]:
    values: set[Decimal] = set()
    for token in tokens:
        normalized = token.replace(",", "")
        is_percent = normalized.endswith("%")
        if is_percent:
            normalized = normalized[:-1]
        try:
            value = Decimal(normalized)
        except InvalidOperation:
            continue
        values.add(value / Decimal("100") if is_percent else value)
    return values


def ai_number_check(db: Session, report: Report, document: ReportDocument) -> dict:
    provenance = document.content.get("ai_provenance")
    if not provenance:
        return {
            "check_id": "QC-008",
            "severity": "BLOCKING",
            "status": "PASSED",
            "actual": {"checked": False, "unmatched": []},
            "threshold": "Every AI-authored number matches a bound metric or selected news citation.",
            "fix_hint": "",
        }
    review = document.content.get("sections", {}).get("month_in_review", {})
    actual_tokens = _numeric_tokens(review)
    allowed_values: set[Decimal] = set()
    if report.active_snapshot_id:
        metrics = db.scalars(select(MetricValue).where(MetricValue.snapshot_id == report.active_snapshot_id))
        for metric in metrics:
            values = _numeric_values({metric.raw_value})
            allowed_values.update(values)
            if metric.unit == "RATIO":
                allowed_values.update(value * Decimal("100") for value in values)
    selected_news = document.content.get("sections", {}).get("company_news", [])
    allowed_values.update(_numeric_values(_numeric_tokens(selected_news)))
    unmatched = sorted(
        token for token in actual_tokens
        if not (_numeric_values({token}) & allowed_values)
    )
    return {
        "check_id": "QC-008",
        "severity": "BLOCKING",
        "status": "FAILED" if unmatched else "PASSED",
        "actual": {"checked": True, "unmatched": unmatched},
        "threshold": "Every AI-authored number matches a bound metric or selected news citation.",
        "fix_hint": "Remove unsupported numbers or insert a bound MetricValue/news citation." if unmatched else "",
    }


def missing_required_slots(payload: dict) -> list[str]:
    """Required slots that have not been applied to this snapshot yet.

    A legacy combined upload satisfies everything it owns in one file, so a snapshot whose
    constituents already carry sector and returns is treated as complete.
    """
    applied = set(payload.get("datasets", {}))
    constituents = payload.get("constituents", [])
    if constituents and all(row.get("sector") for row in constituents) and all(row.get("return_1m") is not None for row in constituents):
        return []
    return [key for key in ingestion.REQUIRED_SLOTS if key not in applied]


def overlay_slot(base: dict, spec: "ingestion.DatasetSpec", payload: dict) -> list[dict]:
    """Write only the fields this slot owns onto the base snapshot, keyed by security code.

    Returns findings describing rows the slot could not be joined to, so a mismatched
    constituent set is visible instead of silently dropped.
    """
    findings: list[dict] = []
    if spec.key == "index_constituents":
        incoming = payload.get("constituents", [])
        existing = {row["security_code"]: row for row in base.get("constituents", [])}
        merged = []
        for row in incoming:
            carried = existing.get(row["security_code"], {})
            # Preserve fields other slots already contributed for this security.
            item = {key: value for key, value in carried.items() if key not in spec.owns}
            item.update(row)
            merged.append(item)
        dropped = sorted(set(existing) - {row["security_code"] for row in incoming}, key=lambda code: int(code) if code.isdigit() else 0)
        for code in dropped:
            findings.append({
                "error_code": "CONSTITUENT_REMOVED", "severity": "INFO", "entity_id": code,
                "message": f"Security {code} is no longer in the index and was removed from the snapshot.",
                "fix_hint": "This is expected when the index rebalances.",
            })
        base["constituents"] = merged
        base["as_of_date"] = incoming[0]["as_of_date"] if incoming else base.get("as_of_date")
        return findings

    rows = payload.get("constituent_returns") or payload.get("sector_mapping") or payload.get("sector_overrides") or []
    by_code = {row["security_code"]: row for row in rows}
    constituents = base.get("constituents", [])
    if not constituents:
        findings.append({
            "error_code": "CONSTITUENT_SET_MISSING", "severity": "BLOCKING", "entity_id": None,
            "message": f"{spec.title} was applied before any index constituents exist.",
            "fix_hint": "Upload the index constituents slot first; it defines which securities the report covers.",
        })
        return findings
    for row in constituents:
        source = by_code.get(row["security_code"])
        if not source:
            continue
        for field in spec.owns:
            if field in source:
                row[field] = source[field]
    unmatched = sorted(set(by_code) - {row["security_code"] for row in constituents}, key=lambda code: int(code) if code.isdigit() else 0)
    for code in unmatched:
        findings.append({
            "error_code": "CONSTITUENT_SET_MISMATCH", "severity": "WARNING", "entity_id": code,
            "message": f"{spec.title} carries security {code}, which is not in the index constituent list.",
            "fix_hint": "The file covers a different index date; the extra row was ignored.",
        })
    uncovered = sorted(
        (row["security_code"] for row in constituents if not any(row.get(field) is not None for field in spec.owns)),
        key=lambda code: int(code) if code.isdigit() else 0,
    )
    error_code = "SECTOR_MAPPING_MISSING" if "sector" in spec.owns else "RETURNS_MISSING"
    for code in uncovered:
        name = next((row.get("name_en") for row in constituents if row["security_code"] == code), code)
        findings.append({
            "error_code": error_code, "severity": "WARNING", "entity_id": code,
            "message": f"{name} ({code}) has no value from {spec.title}.",
            "fix_hint": "Cover this security with an approved sector override, or refresh the vendor file." if "sector" in spec.owns else "Refresh the Bloomberg workbook so this security is included.",
        })
    if spec.key == "sector_overrides":
        base.setdefault("overrides", {})["sector"] = [
            {"security_code": row["security_code"], "sector": row["sector"], "reason": row["reason"], "source": row["source"]}
            for row in rows
        ]
    return findings


def audit(db: Session, action: str, entity_type: str, entity_id: str, request_id: str, details: dict | None = None) -> None:
    db.add(AuditEvent(action=action, entity_type=entity_type, entity_id=entity_id, request_id=request_id, details=details or {}))


def list_products(db: Session, as_of_date, include_inactive: bool = False) -> list[ProductCatalog]:
    query = select(ProductCatalog).where(
        ProductCatalog.valid_from <= as_of_date,
        or_(ProductCatalog.valid_to.is_(None), ProductCatalog.valid_to >= as_of_date),
    )
    if not include_inactive:
        query = query.where(ProductCatalog.is_active.is_(True))
    return list(db.scalars(query.order_by(ProductCatalog.display_order, ProductCatalog.name_en)))


def resolve_product(db: Session, product_code: str, report_date) -> ProductCatalog:
    product = db.scalar(
        select(ProductCatalog)
        .where(
            ProductCatalog.product_code == product_code,
            ProductCatalog.is_active.is_(True),
            ProductCatalog.valid_from <= report_date,
            or_(ProductCatalog.valid_to.is_(None), ProductCatalog.valid_to >= report_date),
        )
        .order_by(ProductCatalog.valid_from.desc())
    )
    if not product:
        raise HTTPException(status_code=422, detail={
            "error_code": "PRODUCT_NOT_AVAILABLE",
            "message": f"Product {product_code} is not configured for {report_date.isoformat()}.",
            "severity": "BLOCKING",
            "fix_hint": "Import an approved product catalog entry with an effective date covering the report date.",
        })
    return product


def import_products(db: Session, rows: list[dict], request_id: str) -> dict[str, int]:
    created = 0
    updated = 0
    now = utcnow()
    for row in rows:
        product = db.scalar(select(ProductCatalog).where(
            ProductCatalog.product_code == row["product_code"],
            ProductCatalog.valid_from == row["valid_from"],
        ))
        if product:
            for field, value in row.items():
                setattr(product, field, value)
            product.source_updated_at = now
            updated += 1
        else:
            db.add(ProductCatalog(**row, source_updated_at=now))
            created += 1
    audit(db, "product_catalog.imported", "product_catalog", "approved-import", request_id, {
        "created": created,
        "updated": updated,
        "total": len(rows),
    })
    db.commit()
    return {"created": created, "updated": updated, "total": len(rows)}


def upsert_news_candidates(db: Session, report: Report, candidates: list[dict], request_id: str, provider: str = "FMP") -> tuple[list[NewsItem], int]:
    snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    ticker_map = {
        str(row.get("ticker", "")).upper(): str(row.get("security_code", ""))
        for row in (snapshot.payload.get("constituents", []) if snapshot else [])
        if row.get("ticker")
    }
    items: list[NewsItem] = []
    created = 0
    for candidate in candidates:
        ticker = candidate.get("ticker")
        security_code = ticker_map.get(str(ticker or "").upper())
        item = db.scalar(select(NewsItem).where(NewsItem.source_url == candidate["source_url"]))
        report_ids: list[str]
        if item:
            metadata = dict(item.metadata_json or {})
            report_ids = list(metadata.get("report_ids", []))
            if report.id not in report_ids:
                report_ids.append(report.id)
            metadata.update(candidate["metadata_json"])
            metadata["report_ids"] = report_ids
            item.metadata_json = metadata
        else:
            metadata = {**candidate["metadata_json"], "report_ids": [report.id]}
            importance_score = metadata.get("importance_score")
            importance = (
                "HIGH" if isinstance(importance_score, (int, float)) and importance_score >= 70
                else "LOW" if isinstance(importance_score, (int, float)) and importance_score < 40
                else "MEDIUM"
            )
            item = NewsItem(
                source_name=candidate["source_name"], source_url=candidate["source_url"],
                published_at=candidate["published_at"], title=candidate["title"], summary=candidate["summary"],
                security_code=security_code, ticker=ticker, importance=importance,
                match_confidence=100 if security_code else 0, metadata_json=metadata,
            )
            db.add(item)
            created += 1
        db.flush()
        relation = db.scalar(select(ReportNewsCandidate).where(
            ReportNewsCandidate.report_id == report.id,
            ReportNewsCandidate.news_item_id == item.id,
        ))
        if relation is None:
            metadata = candidate.get("metadata_json") or {}
            db.add(ReportNewsCandidate(
                report_id=report.id,
                news_item_id=item.id,
                provider=provider,
                match_status="CONFIRMED" if security_code or metadata.get("matched_security_code") else "NEEDS_REVIEW",
                match_evidence={
                    key: metadata.get(key)
                    for key in ("matched_security_code", "matched_alias", "match_method", "external_id")
                    if metadata.get(key) is not None
                },
            ))
        items.append(item)
    db.flush()
    action = "news.manually_added" if provider == "MANUAL" else f"news.{provider.lower()}_fetched"
    audit(db, action, "report", report.id, request_id, {"provider": provider, "fetched": len(candidates), "created": created})
    db.commit()
    for item in items:
        db.refresh(item)
    return items, created


def list_report_news_candidates(db: Session, report_id: str) -> list[NewsItem]:
    related = list(db.scalars(
        select(NewsItem)
        .join(ReportNewsCandidate, ReportNewsCandidate.news_item_id == NewsItem.id)
        .where(ReportNewsCandidate.report_id == report_id)
        .order_by(NewsItem.published_at.desc())
    ))
    related_ids = {item.id for item in related}
    legacy = [
        item for item in db.scalars(select(NewsItem).order_by(NewsItem.published_at.desc()))
        if item.id not in related_ids and report_id in (item.metadata_json or {}).get("report_ids", [])
    ]
    return sorted([*related, *legacy], key=lambda item: item.published_at, reverse=True)


def create_report(db: Session, command: ReportCreate, request_id: str) -> Report:
    product = resolve_product(db, command.product_code, command.report_date)
    report = Report(
        product_code=product.product_code,
        product_name=f"{product.name_en} ({product.ticker})",
        constituent_index_code=product.constituent_index_code,
        benchmark_instrument_code=product.benchmark_instrument_code,
        benchmark_code=product.constituent_index_code,
        report_date=command.report_date,
        language_mode=command.language_mode,
        template_version=product.template_version,
    )
    db.add(report)
    db.flush()
    content = initial_document(
        report.id,
        report.report_date,
        product.template_version,
        product.design_token_version,
        product.ticker,
        product.benchmark_instrument_name or product.benchmark_instrument_code,
    )
    document = ReportDocument(
        report_id=report.id,
        version=1,
        template_version=product.template_version,
        language_mode=report.language_mode,
        content=content,
        checksum=checksum(content),
    )
    db.add(document)
    audit(db, "report.created", "report", report.id, request_id)
    db.commit()
    db.refresh(report)
    return report


def get_report(db: Session, report_id: str) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail={"error_code": "REPORT_NOT_FOUND", "message": "Report not found."})
    return report


def latest_document(db: Session, report_id: str) -> ReportDocument:
    document = db.scalar(select(ReportDocument).where(ReportDocument.report_id == report_id).order_by(ReportDocument.version.desc()))
    if not document:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": "Report document not found."})
    return document


def fixture_payload(product_code: str, report_date) -> dict:
    if product_code != "3033" or report_date.isoformat() != "2026-06-30":
        raise HTTPException(status_code=422, detail={
            "error_code": "FIXTURE_NOT_AVAILABLE",
            "message": f"No approved golden fixture exists for {product_code} on {report_date.isoformat()}.",
            "severity": "BLOCKING",
            "fix_hint": "Use an approved CDB snapshot or upload a complete dataset for this product.",
        })
    path: Path = settings.service_root / "tests" / "fixtures" / "3033_202606" / "snapshot.json"
    if not path.exists():
        raise HTTPException(status_code=503, detail={"error_code": "FIXTURE_MISSING", "message": f"Golden fixture is missing: {path}"})
    payload = json.loads(path.read_text(encoding="utf-8"))
    editorial_path = path.with_name("editorial.json")
    if editorial_path.exists():
        payload.update(json.loads(editorial_path.read_text(encoding="utf-8")))
    return payload


def create_snapshot(db: Session, report: Report, source_policy: str, mapping_version: str, request_id: str) -> DataSnapshot:
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED", "message": "Create a revision before refreshing data."})
    if source_policy != "GOLDEN_FIXTURE":
        raise HTTPException(status_code=422, detail={
            "error_code": "CONNECTOR_NOT_CONFIGURED",
            "message": f"{source_policy} is not configured in this environment.",
            "severity": "BLOCKING",
            "fix_hint": "Configure the approved CDB connector or use the golden fixture in local/UAT.",
        })
    product = resolve_product(db, report.product_code, report.report_date)
    payload = fixture_payload(report.product_code, report.report_date)
    results = quality_checks(payload, product.expected_constituent_count)
    valid = all(item["status"] == "PASSED" for item in results if item["severity"] == "BLOCKING")
    snapshot = DataSnapshot(
        report_id=report.id,
        as_of_date=report.report_date,
        source_policy=source_policy,
        mapping_version=mapping_version,
        status=SnapshotStatus.VALID if valid else SnapshotStatus.INVALID,
        checksum=checksum(payload),
        payload=payload,
        quality_results=results,
    )
    db.add(snapshot)
    db.flush()
    ensure_snapshot_datasets(db, snapshot)
    if valid:
        report.active_snapshot_id = snapshot.id
        report.status = ReportStatus.DATA_READY
        current = latest_document(db, report.id)
        bound = bind_snapshot(current.content, payload)
        bound["snapshot_id"] = snapshot.id
        next_document = ReportDocument(
            report_id=report.id,
            version=current.version + 1,
            snapshot_id=snapshot.id,
            template_version=report.template_version,
            language_mode=report.language_mode,
            content=bound,
            checksum=checksum(bound),
        )
        db.add(next_document)
        report.version += 1
    audit(db, "snapshot.created", "snapshot", snapshot.id, request_id, {"status": snapshot.status.value})
    db.commit()
    db.refresh(snapshot)
    return snapshot


def apply_import(db: Session, report: Report, data_import: DataImport, reason: str, request_id: str) -> DataSnapshot:
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED", "message": "Create a revision before applying an import."})
    if data_import.report_id != report.id:
        raise HTTPException(status_code=404, detail={"error_code": "IMPORT_NOT_FOUND"})
    if data_import.status != "VALIDATED":
        raise HTTPException(status_code=409, detail={"error_code": "IMPORT_NOT_APPLICABLE", "message": "Import is not in VALIDATED state."})
    product = resolve_product(db, report.product_code, report.report_date)
    active_snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    if active_snapshot:
        base = json.loads(json.dumps(active_snapshot.payload))
    else:
        base = empty_payload(report.report_date)
    spec = ingestion.get_spec(data_import.dataset_type)
    findings: list[dict] = []
    if data_import.dataset_type == "historical_performance":
        if not active_snapshot:
            raise HTTPException(status_code=422, detail={"error_code": "BASE_SNAPSHOT_REQUIRED", "message": "Historical Performance requires an active snapshot to preserve the remaining report datasets."})
        base["total_return_series"] = data_import.payload["total_return_series"]
        base["historical_performance"] = data_import.payload["historical_performance"]
    elif data_import.dataset_type == "final_analytics":
        base["constituents"] = data_import.payload["constituents"]
        base["fund_kpis"] = data_import.payload["fund_kpis"]
        base["trading_calendar"] = data_import.payload["trading_calendar"]
        base["index_events"] = data_import.payload.get("index_events", [])
        base["constituent_index_code"] = report.constituent_index_code
        base["analytics"] = {"top10": [], "sectors": [], "top": [], "bottom": [], "portfolio": []}
    elif data_import.dataset_type == "constituents":
        base["constituents"] = data_import.payload["constituents"]
    else:
        findings = overlay_slot(base, spec, data_import.payload)
    from .industry import map_effective_hsics
    findings.extend(map_effective_hsics(db, base, report.report_date))
    base.setdefault("datasets", {})[data_import.dataset_type] = {
        "import_id": data_import.id,
        "filename": data_import.original_filename,
        "checksum": data_import.checksum,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    results = quality_checks(base, product.expected_constituent_count)
    missing = missing_required_slots(base)
    blocked = [item for item in results if item["severity"] == "BLOCKING" and item["status"] != "PASSED"]
    blocked.extend(item for item in findings if item.get("severity") == "BLOCKING" and item.get("status", "FAILED") != "PASSED")
    # A slot upload is incomplete by design until every required slot has landed, so an incomplete
    # snapshot is recorded as PENDING rather than rejected. Only a snapshot that is complete *and*
    # passes every blocking check becomes VALID and therefore calculable.
    complete = not missing
    if complete and blocked and data_import.dataset_type in {"constituents", "historical_performance", "final_analytics"}:
        raise HTTPException(status_code=422, detail={"error_code": "IMPORT_QUALITY_BLOCKED", "checks": blocked})
    status = SnapshotStatus.VALID if complete and not blocked else SnapshotStatus.PENDING
    snapshot = DataSnapshot(
        report_id=report.id,
        as_of_date=report.report_date,
        source_policy="UPLOAD_OVERRIDE",
        mapping_version=data_import.parser_version,
        status=status,
        checksum=checksum(base),
        payload=base,
        quality_results=[*results, *findings],
    )
    db.add(snapshot); db.flush()
    ensure_snapshot_datasets(db, snapshot)
    report.active_snapshot_id = snapshot.id
    report.status = (
        ReportStatus.DATA_READY if status == SnapshotStatus.VALID
        else ReportStatus.QA_BLOCKED if complete and blocked
        else ReportStatus.DRAFT
    )
    current = latest_document(db, report.id)
    bound = bind_snapshot(current.content, base)
    bound["snapshot_id"] = snapshot.id
    next_document = ReportDocument(
        report_id=report.id, version=current.version + 1, snapshot_id=snapshot.id,
        template_version=report.template_version, language_mode=report.language_mode,
        content=bound, checksum=checksum(bound),
    )
    db.add(next_document)
    report.version += 1
    data_import.status = "APPLIED"
    data_import.reason = reason
    data_import.applied_snapshot_id = snapshot.id
    audit(db, "import.applied", "import", data_import.id, request_id, {
        "reason": reason, "snapshot_id": snapshot.id, "dataset_type": data_import.dataset_type,
        "snapshot_status": status.value, "missing_slots": missing, "findings": len(findings),
    })
    db.commit(); db.refresh(snapshot)
    return snapshot


def update_document(db: Session, report: Report, expected_version: int, content: dict, request_id: str) -> ReportDocument:
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED", "message": "Finalized reports are immutable."})
    current = latest_document(db, report.id)
    if current.version != expected_version:
        raise HTTPException(status_code=409, detail={
            "error_code": "VERSION_CONFLICT",
            "message": "Document was changed by another editor.",
            "current_version": current.version,
            "current_checksum": current.checksum,
        })
    product = resolve_product(db, report.product_code, report.report_date)
    canonical = dict(content)
    canonical.update({
        "report_id": report.id,
        "report_date": report.report_date.isoformat(),
        "month_name": report.report_date.strftime("%B"),
        "product_ticker": product.ticker,
        "benchmark_name": product.benchmark_instrument_name or product.benchmark_instrument_code,
        "template_version": report.template_version,
        "design_token_version": product.design_token_version,
        "language_mode": report.language_mode,
        "snapshot_id": report.active_snapshot_id,
    })
    try:
        content = validate_document_content(canonical)
    except DocumentValidationError as error:
        raise HTTPException(status_code=422, detail={
            "error_code": error.error_code,
            "field": error.field,
            "entity_id": error.entity_id,
            "message": str(error),
            "severity": "BLOCKING",
            "fix_hint": error.fix_hint,
        }) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail={
            "error_code": "REVIEW_LAYOUT_INVALID",
            "message": str(error),
            "severity": "BLOCKING",
            "fix_hint": "Keep every Review block inside the 12-column canvas without overlap.",
        }) from error
    document = ReportDocument(
        report_id=report.id,
        version=current.version + 1,
        snapshot_id=report.active_snapshot_id,
        template_version=report.template_version,
        language_mode=report.language_mode,
        content=content,
        checksum=checksum(content),
    )
    db.add(document)
    if report.status in {ReportStatus.DATA_READY, ReportStatus.READY_TO_FINALIZE, ReportStatus.REVIEW}:
        report.status = ReportStatus.EDITING
    report.version += 1
    audit(db, "document.updated", "report", report.id, request_id, {"document_version": document.version})
    db.commit()
    db.refresh(document)
    return document


def finalize(db: Session, report: Report, expected_version: int, request_id: str) -> Report:
    if report.status == ReportStatus.FINALIZED:
        return report
    document = latest_document(db, report.id)
    if document.version != expected_version:
        raise HTTPException(status_code=409, detail={"error_code": "VERSION_CONFLICT", "current_version": document.version})
    if not report.active_snapshot_id:
        raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED", "message": "A valid active snapshot is required."})
    snapshot = db.get(DataSnapshot, report.active_snapshot_id)

    def qa_block(detail: dict) -> None:
        report.status = ReportStatus.QA_BLOCKED
        db.commit()
        raise HTTPException(status_code=422, detail=detail)

    try:
        require_complete_snapshot(snapshot)
    except HTTPException as error:
        if isinstance(error.detail, dict):
            qa_block(error.detail)
        raise
    module_codes = set(db.scalars(select(ModuleSnapshot.module_code).where(ModuleSnapshot.snapshot_id == snapshot.id)))
    required_modules = {"historical_performance", "constituents_performance", "final_analytics", "footnotes"}
    missing_modules = sorted(required_modules - module_codes)
    if missing_modules:
        qa_block({
            "error_code": "CALCULATION_REQUIRED",
            "message": "The active snapshot has not produced every required module snapshot.",
            "severity": "BLOCKING",
            "fix_hint": "Run the server calculation for the active snapshot before finalization.",
            "missing_modules": missing_modules,
        })
    if snapshot.source_policy != "GOLDEN_FIXTURE":
        dataset_types = set(db.scalars(select(SnapshotDataset.dataset_type).where(SnapshotDataset.snapshot_id == snapshot.id)))
        if "industry_master" not in dataset_types:
            qa_block({
                "error_code": "IND-001",
                "message": "The active snapshot is not bound to one report-date-effective HSICS master.",
                "severity": "BLOCKING",
                "fix_hint": "Import the formal HSICS version and create a new complete snapshot.",
            })
    # quality_results mixes check results (which carry `status`) with overlay findings (which do
    # not); an unresolved finding is a failure by default.
    failures = [item for item in snapshot.quality_results if item["severity"] == "BLOCKING" and item.get("status", "FAILED") != "PASSED"]
    if failures:
        qa_block({"error_code": "QUALITY_BLOCKED", "checks": failures})
    calculation_failures = list(db.scalars(select(QualityCheckResult).where(
        QualityCheckResult.snapshot_id == snapshot.id,
        QualityCheckResult.severity == "BLOCKING",
        QualityCheckResult.status != "PASSED",
    )))
    if calculation_failures:
        qa_block({
            "error_code": "QUALITY_BLOCKED",
            "checks": [{
                "check_id": item.check_id,
                "severity": item.severity,
                "status": item.status,
                "entity_id": item.entity_id,
                "actual": item.actual,
                "threshold": item.threshold,
                "fix_hint": item.fix_hint,
            } for item in calculation_failures],
        })
    number_check = ai_number_check(db, report, document)
    if number_check["status"] != "PASSED":
        qa_block({"error_code": "QC-008", "checks": [number_check]})
    if "Add the approved" in json.dumps(document.content, ensure_ascii=False):
        qa_block({"error_code": "EDITORIAL_PLACEHOLDERS", "message": "Replace all editorial placeholders before finalization."})
    report.status = ReportStatus.READY_TO_FINALIZE
    report.finalized_document_version = document.version
    report.status = ReportStatus.FINALIZED
    report.version += 1
    audit(db, "report.finalized", "report", report.id, request_id, {"document_version": document.version})
    db.commit()
    db.refresh(report)
    return report


def create_revision(db: Session, source: Report, reason: str, request_id: str) -> Report:
    if source.status != ReportStatus.FINALIZED:
        raise HTTPException(status_code=422, detail={"error_code": "FINALIZED_SOURCE_REQUIRED", "message": "Only a finalized report can be revised."})
    source_document = latest_document(db, source.id)
    report = Report(
        product_code=source.product_code, product_name=source.product_name,
        constituent_index_code=source.constituent_index_code,
        benchmark_instrument_code=source.benchmark_instrument_code,
        benchmark_code=source.benchmark_code,
        report_date=source.report_date, language_mode=source.language_mode, status=ReportStatus.DRAFT,
        revision=source.revision + 1, active_snapshot_id=source.active_snapshot_id,
        parent_report_id=source.id, revision_reason=reason, template_version=source.template_version,
    )
    db.add(report); db.flush()
    content = dict(source_document.content)
    content["report_id"] = report.id
    document = ReportDocument(
        report_id=report.id, version=1, snapshot_id=source.active_snapshot_id,
        template_version=source.template_version, language_mode=source.language_mode,
        content=content, checksum=checksum(content),
    )
    db.add(document)
    audit(db, "report.revision_created", "report", report.id, request_id, {"source_report_id": source.id, "reason": reason})
    db.commit(); db.refresh(report)
    return report


def require_complete_snapshot(snapshot: DataSnapshot | None) -> None:
    """Reject work that would present an incomplete snapshot as finished output.

    A PENDING snapshot is a legitimate intermediate state while slots are still being uploaded,
    but calculating or finalizing from one would publish blanks as if they were facts.
    """
    if snapshot is None:
        raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED", "message": "This report has no active data snapshot."})
    if snapshot.status == SnapshotStatus.VALID:
        return
    missing = missing_required_slots(snapshot.payload or {})
    titles = [ingestion.REGISTRY[key].title for key in missing if key in ingestion.REGISTRY]
    raise HTTPException(status_code=422, detail={
        "error_code": "SNAPSHOT_INCOMPLETE",
        "message": "The active snapshot is not complete enough to calculate from." if missing else "The active snapshot failed its blocking quality checks.",
        "severity": "BLOCKING",
        "fix_hint": f"Upload the remaining dataset(s): {', '.join(titles)}." if titles else "Resolve the reported quality check failures and apply the dataset again.",
        "missing_slots": missing,
        "snapshot_status": snapshot.status.value,
    })


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
    analytics, metrics = calculate_snapshot(derived_payload)
    if metrics.get("next_rebalancing_date"):
        derived_payload["next_rebalancing_date"] = metrics["next_rebalancing_date"]
    derived_payload.update({"analytics": analytics, "metrics": metrics, "formula_version": formula_version})
    derived_payload["footnotes"] = build_lineage_footnotes(derived_payload, metrics)
    results = quality_checks(derived_payload, product.expected_constituent_count)
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
    content = bind_snapshot(current.content, derived_payload)
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


def ai_assisted_draft(db: Session, report: Report, expected_version: int, user_prompt: str, request_id: str) -> ReportDocument:
    current = latest_document(db, report.id)
    if current.version != expected_version:
        raise HTTPException(status_code=409, detail={"error_code": "VERSION_CONFLICT", "current_version": current.version})
    if not report.active_snapshot_id:
        raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED"})
    snapshot = db.get(DataSnapshot, report.active_snapshot_id)
    metrics = snapshot.payload.get("metrics")
    if not metrics:
        _, metrics = calculate_snapshot(snapshot.payload)
    content = json.loads(json.dumps(current.content))
    month = content["month_name"]
    content["sections"]["month_in_review"]["summary"] = (
        f"During {month}, the {report.benchmark_code} constituent set contained {metrics['constituent_count']} constituents across "
        f"{metrics['sector_count']} mapped sectors. Performance remained differentiated; the strongest one-month "
        f"constituent was security {metrics['top_security_code']}, while security {metrics['bottom_security_code']} was the weakest."
    )
    content["sections"]["month_in_review"]["drivers"] = [{"title": "Differentiated constituent performance", "body": "Review the bound Top and Bottom Performers data and approved company news before publication."}]
    content["sections"]["month_in_review"]["monitor"] = [{"title": "Earnings delivery and liquidity", "body": "Monitor company guidance, external liquidity conditions, and evidence of sustainable earnings growth."}]
    content["sections"]["month_in_review"]["outlook"] = user_prompt or "Complete the outlook using approved investment commentary."
    content["ai_provenance"] = {
        "provider": "deterministic-template",
        "model": "no-external-model",
        "prompt_version": "in-review-v1",
        "metric_bindings": ["constituent_count", "sector_count", "top_security_code", "bottom_security_code"],
    }
    return update_document(db, report, current.version, content, request_id)
