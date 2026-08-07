from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from .calculation import calculate_snapshot, quality_checks
from .document import bind_snapshot, checksum, initial_document, validate_document_content
from .models import AuditEvent, DataImport, DataSnapshot, NewsItem, ProductCatalog, Report, ReportDocument, ReportStatus, SnapshotStatus, utcnow
from .schemas import ReportCreate


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


def upsert_news_candidates(db: Session, report: Report, candidates: list[dict], request_id: str) -> tuple[list[NewsItem], int]:
    snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    ticker_map = {
        str(row.get("ticker", "")).upper(): str(row.get("security_code", ""))
        for row in (snapshot.payload.get("constituents", []) if snapshot else [])
        if row.get("ticker")
    }
    items: list[NewsItem] = []
    created = 0
    for candidate in candidates:
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
            ticker = candidate.get("ticker")
            security_code = ticker_map.get(str(ticker or "").upper())
            metadata = {**candidate["metadata_json"], "report_ids": [report.id]}
            item = NewsItem(
                source_name=candidate["source_name"], source_url=candidate["source_url"],
                published_at=candidate["published_at"], title=candidate["title"], summary=candidate["summary"],
                security_code=security_code, ticker=ticker, importance="MEDIUM",
                match_confidence=100 if security_code else 0, metadata_json=metadata,
            )
            db.add(item)
            created += 1
        items.append(item)
    db.flush()
    audit(db, "news.fmp_fetched", "report", report.id, request_id, {"provider": "FMP", "fetched": len(candidates), "created": created})
    db.commit()
    for item in items:
        db.refresh(item)
    return items, created


def create_report(db: Session, command: ReportCreate, request_id: str) -> Report:
    product = resolve_product(db, command.product_code, command.report_date)
    report = Report(
        product_code=product.product_code,
        product_name=f"{product.name_en} ({product.ticker})",
        benchmark_code=product.benchmark_code,
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
        product.benchmark_name or product.benchmark_code,
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
    path: Path = settings.workspace_root / "tests" / "fixtures" / "3033_202606" / "snapshot.json"
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
    if valid:
        report.active_snapshot_id = snapshot.id
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
    elif report.product_code == "3033" and report.report_date.isoformat() == "2026-06-30":
        base = fixture_payload(report.product_code, report.report_date)
    else:
        base = {
            "as_of_date": report.report_date.isoformat(),
            "constituents": [],
            "historical_performance": {"rows": []},
            "company_news": [],
            "analytics": {"top10": [], "sectors": [], "top": [], "bottom": [], "portfolio": []},
            "footnotes": {},
        }
    if data_import.dataset_type == "historical_performance":
        if not active_snapshot:
            raise HTTPException(status_code=422, detail={"error_code": "BASE_SNAPSHOT_REQUIRED", "message": "Historical Performance requires an active snapshot to preserve the remaining report datasets."})
        base["total_return_series"] = data_import.payload["total_return_series"]
        base["historical_performance"] = data_import.payload["historical_performance"]
    elif data_import.dataset_type == "final_analytics":
        base["constituents"] = data_import.payload["constituents"]
        base["fund_kpis"] = data_import.payload["fund_kpis"]
        base["analytics"] = {"top10": [], "sectors": [], "top": [], "bottom": [], "portfolio": []}
    else:
        base["constituents"] = data_import.payload["constituents"]
    results = quality_checks(base, product.expected_constituent_count)
    failures = [item for item in results if item["severity"] == "BLOCKING" and item["status"] != "PASSED"]
    if failures:
        raise HTTPException(status_code=422, detail={"error_code": "IMPORT_QUALITY_BLOCKED", "checks": failures})
    snapshot = DataSnapshot(
        report_id=report.id,
        as_of_date=report.report_date,
        source_policy="UPLOAD_OVERRIDE",
        mapping_version=data_import.parser_version,
        status=SnapshotStatus.VALID,
        checksum=checksum(base),
        payload=base,
        quality_results=results,
    )
    db.add(snapshot); db.flush()
    report.active_snapshot_id = snapshot.id
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
    audit(db, "import.applied", "import", data_import.id, request_id, {"reason": reason, "snapshot_id": snapshot.id, "dataset_type": data_import.dataset_type})
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
    try:
        content = validate_document_content(content)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={
            "error_code": "REVIEW_LAYOUT_INVALID",
            "message": str(error),
            "severity": "BLOCKING",
            "fix_hint": "Keep every Review block inside the 12-column canvas without overlap.",
        }) from error
    content["report_id"] = report.id
    content["snapshot_id"] = report.active_snapshot_id
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
    failures = [item for item in snapshot.quality_results if item["severity"] == "BLOCKING" and item["status"] != "PASSED"]
    if failures:
        raise HTTPException(status_code=422, detail={"error_code": "QUALITY_BLOCKED", "checks": failures})
    if "Add the approved" in json.dumps(document.content, ensure_ascii=False):
        raise HTTPException(status_code=422, detail={"error_code": "EDITORIAL_PLACEHOLDERS", "message": "Replace all editorial placeholders before finalization."})
    report.status = ReportStatus.FINALIZED
    report.finalized_document_version = document.version
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
        product_code=source.product_code, product_name=source.product_name, benchmark_code=source.benchmark_code,
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


def run_calculation(db: Session, report: Report, request_id: str) -> tuple[dict, ReportDocument, list[dict]]:
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    if not report.active_snapshot_id:
        raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED"})
    snapshot = db.get(DataSnapshot, report.active_snapshot_id)
    product = resolve_product(db, report.product_code, report.report_date)
    formula_version = product.formula_profile
    derived_payload = json.loads(json.dumps(snapshot.payload))
    analytics, metrics = calculate_snapshot(derived_payload)
    derived_payload.update({"analytics": analytics, "metrics": metrics, "formula_version": formula_version})
    results = quality_checks(derived_payload, product.expected_constituent_count)
    current = latest_document(db, report.id)
    content = bind_snapshot(current.content, derived_payload)
    content["formula_version"] = formula_version
    document = ReportDocument(
        report_id=report.id, version=current.version + 1, snapshot_id=snapshot.id,
        template_version=report.template_version, language_mode=report.language_mode,
        content=content, checksum=checksum(content),
    )
    db.add(document); report.version += 1
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
