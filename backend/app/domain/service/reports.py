"""Report lifecycle and the release gate.

Creation, lookup, revision and finalize, plus the checks that decide whether a report may be
finalized at all. The gate lives here rather than in ``documents`` because it is the report's
own admission control: it reads across the snapshot, the persisted quality results and the
document in one place.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from ..document import checksum, initial_document
from ..models import (
    DataSnapshot,
    Lane,
    MetricValue,
    ModuleSnapshot,
    QualityCheckResult,
    Report,
    ReportDocument,
    ReportStatus,
    SnapshotDataset,
)
from ..schemas import ReportCreate
from .audit import audit
from .catalog import resolve_product
from .documents import latest_document
from .snapshots import _stage_auto_snapshot, has_approved_constituent_bundle, require_complete_snapshot


_NUMBER_TOKEN = re.compile(r"(?<![\w.])[+-]?\d[\d,]*(?:\.\d+)?%?")


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
    db.flush()
    if settings.da_report_auto_load:
        _stage_auto_snapshot(db, report, product, request_id, preserve_constituents=False)
    audit(db, "report.created", "report", report.id, request_id)
    db.commit()
    db.refresh(report)
    return report


def get_report(db: Session, report_id: str) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail={"error_code": "REPORT_NOT_FOUND", "message": "Report not found."})
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
        lane=source.lane,
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


def release_gate_checks(db: Session, report: Report, document: ReportDocument) -> list[dict]:
    checks: list[dict] = []
    snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    lane = snapshot.lane if snapshot else report.lane
    # Not blocking: a testing report is allowed to be finalized and rendered, because that is how the
    # render pipeline is regressed. It must never be silent about it — the reviewer sees this, and
    # every artifact carries the watermark and the TESTING- filename prefix.
    checks.append({
        "check_id": "LANE-001",
        "severity": "WARNING",
        "status": "WARNING" if lane == Lane.TESTING.value else "PASSED",
        "actual": {"lane": lane, "source_policy": snapshot.source_policy if snapshot else None},
        "fix_hint": (
            "This report is bound to testing data. Its artifacts are watermarked and must not be distributed."
            if lane == Lane.TESTING.value else ""
        ),
    })
    try:
        require_complete_snapshot(snapshot)
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        checks.append({
            "check_id": str(detail.get("error_code") or "SNAPSHOT_REQUIRED"),
            "severity": "BLOCKING",
            "status": "FAILED",
            "fix_hint": str(detail.get("fix_hint") or "Create a complete valid snapshot."),
        })
        snapshot = None
    if snapshot:
        checks.append({
            "check_id": "CONSTITUENT_SOURCES_REQUIRED",
            "severity": "BLOCKING",
            "status": (
                "PASSED"
                if snapshot.lane != Lane.PRODUCTION.value or has_approved_constituent_bundle(snapshot.payload or {})
                else "FAILED"
            ),
            "actual": {"lane": snapshot.lane, "approved_sources": has_approved_constituent_bundle(snapshot.payload or {})},
            "fix_hint": (
                "Apply HSTECH constituent identity data and load returns from FMP or an approved upload."
                if snapshot.lane == Lane.PRODUCTION.value and not has_approved_constituent_bundle(snapshot.payload or {})
                else ""
            ),
        })
        module_codes = set(db.scalars(select(ModuleSnapshot.module_code).where(ModuleSnapshot.snapshot_id == snapshot.id)))
        missing_modules = sorted({"historical_performance", "constituents_performance", "final_analytics", "footnotes"} - module_codes)
        checks.append({
            "check_id": "CALCULATION_REQUIRED",
            "severity": "BLOCKING",
            "status": "FAILED" if missing_modules else "PASSED",
            "actual": {"missing_modules": missing_modules},
            "fix_hint": "Run the server calculation for the active snapshot." if missing_modules else "",
        })
        # IND-001 applies to every lane. It used to be skipped for GOLDEN_FIXTURE, and the skip was
        # invisible: the check simply vanished from the response, so a reviewer could not tell
        # whether it had passed or had never run.
        dataset_types = set(db.scalars(select(SnapshotDataset.dataset_type).where(SnapshotDataset.snapshot_id == snapshot.id)))
        checks.append({
            "check_id": "IND-001",
            "severity": "BLOCKING",
            "status": "PASSED" if "industry_master" in dataset_types else "FAILED",
            "actual": {"lane": snapshot.lane},
            "fix_hint": "Import the formal report-date HSICS version and apply the constituent dataset again." if "industry_master" not in dataset_types else "",
        })
        for item in snapshot.quality_results or []:
            checks.append({
                "check_id": item.get("check_id") or item.get("error_code") or "SNAPSHOT_QUALITY",
                "severity": item.get("severity", "BLOCKING"),
                "status": item.get("status", "FAILED"),
                "actual": item.get("actual"),
                "fix_hint": item.get("fix_hint", ""),
            })
        for item in db.scalars(select(QualityCheckResult).where(QualityCheckResult.snapshot_id == snapshot.id)):
            checks.append({
                "check_id": item.check_id,
                "severity": item.severity,
                "status": item.status,
                "actual": item.actual,
                "fix_hint": item.fix_hint,
            })
    document_text = json.dumps(document.content, ensure_ascii=False)
    placeholders = any(marker in document_text for marker in ("Add the approved", "Add monthly market review.", "Add outlook."))
    checks.append({
        "check_id": "QC-009",
        "severity": "BLOCKING",
        "status": "FAILED" if placeholders else "PASSED",
        "fix_hint": "Replace all editorial placeholders." if placeholders else "",
    })
    selected_news = document.content.get("sections", {}).get("company_news", [])
    news_after_report_date = sorted({
        str(item.get("published_at", ""))
        for item in selected_news
        if str(item.get("published_at", ""))[:10] > report.report_date.isoformat()
    })
    checks.append({
        "check_id": "NEWS_AFTER_REPORT_DATE",
        "severity": "WARNING",
        "status": "WARNING" if news_after_report_date else "PASSED",
        "actual": {"published_at": news_after_report_date},
        "fix_hint": "Confirm that post-report-date news is intentionally included." if news_after_report_date else "",
    })
    checks.append(ai_number_check(db, report, document))
    return checks


def finalize(db: Session, report: Report, expected_version: int, request_id: str) -> Report:
    if report.status == ReportStatus.FINALIZED:
        return report
    document = latest_document(db, report.id)
    if document.version != expected_version:
        raise HTTPException(status_code=409, detail={"error_code": "VERSION_CONFLICT", "current_version": document.version})
    if not report.active_snapshot_id:
        raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED", "message": "A valid active snapshot is required."})

    def qa_block(detail: dict) -> None:
        report.status = ReportStatus.QA_BLOCKED
        db.commit()
        raise HTTPException(status_code=422, detail=detail)

    gate_failures = [
        item for item in release_gate_checks(db, report, document)
        if item.get("severity") == "BLOCKING" and item.get("status") != "PASSED"
    ]
    if gate_failures:
        first = gate_failures[0]
        check_id = str(first.get("check_id") or "QUALITY_BLOCKED")
        error_code = {
            "QC-008": "QC-008",
            "QC-009": "EDITORIAL_PLACEHOLDERS",
            "CALCULATION_REQUIRED": "CALCULATION_REQUIRED",
            "IND-001": "IND-001",
            "SNAPSHOT_REQUIRED": "SNAPSHOT_REQUIRED",
            "SNAPSHOT_INCOMPLETE": "SNAPSHOT_INCOMPLETE",
        }.get(check_id, "QUALITY_BLOCKED")
        qa_block({
            "error_code": error_code,
            "message": first.get("fix_hint") or "The report failed a release gate.",
            "checks": gate_failures,
        })

    report.status = ReportStatus.READY_TO_FINALIZE
    report.finalized_document_version = document.version
    report.status = ReportStatus.FINALIZED
    report.version += 1
    audit(db, "report.finalized", "report", report.id, request_id, {"document_version": document.version})
    db.commit()
    db.refresh(report)
    return report
