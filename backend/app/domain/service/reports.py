"""Report lifecycle and advisory release checks.

Creation, lookup, revision and finalize, plus the checks that describe release readiness. The
checks live here rather than in ``documents`` because they read across the snapshot, persisted
quality results and document in one place. Under ADR-0014 they remain visible through Review and
the audit trail, but do not block finalization.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from ..document import bind_snapshot, checksum, initial_document
from ..localization import (
    ZH_HANS,
    chinese_content_warnings,
    localized_source_text,
    traditional_to_simplified,
)
from ..models import (
    DataSnapshot,
    Lane,
    MetricValue,
    ModuleSnapshot,
    QualityCheckResult,
    Report,
    ReportDocument,
    ReportNewsCandidate,
    ReportNewsSelection,
    ReportStatus,
    SnapshotDataset,
    NewsItem,
)
from ..schemas import LanguageVariantCreate, ReportCreate
from .audit import audit
from .catalog import resolve_product
from .documents import latest_document
from .snapshots import _stage_auto_snapshot, has_approved_constituent_bundle, require_complete_snapshot


_NUMBER_TOKEN = re.compile(r"(?<![\w.])[+-]?\d[\d,]*(?:\.\d+)?%?")


def create_report(db: Session, command: ReportCreate, request_id: str) -> Report:
    product = resolve_product(db, command.product_code, command.report_date)
    report = Report(
        product_code=product.product_code,
        product_name=f"{localized_source_text(language_mode=command.language_mode, en=product.name_en, zh_hans=product.name_zh_hans, zh_hant=product.name_zh_hant)[0] or product.ticker} ({product.ticker})",
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
        command.language_mode,
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


_REVIEW_BLOCK_TITLES = {
    "summary": {"EN": "Monthly Review", ZH_HANS: "月度回顾"},
    "drivers": {"EN": "Key Drivers", ZH_HANS: "主要驱动因素"},
    "monitor": {"EN": "Key Areas to Monitor", ZH_HANS: "重点关注领域"},
    "outlook": {"EN": "Outlook", ZH_HANS: "展望"},
}


def _copy_review_layout(source: dict, target: dict, language_mode: str) -> None:
    source_review = (source.get("sections") or {}).get("month_in_review") or {}
    blocks = source_review.get("blocks")
    if not isinstance(blocks, list):
        return
    target_review = target["sections"]["month_in_review"]
    target_blocks: list[dict] = []
    for block in blocks:
        copied = {
            key: deepcopy(value)
            for key, value in block.items()
            if key not in {"title", "content"}
        }
        block_id = str(block.get("block_id") or "")
        title = _REVIEW_BLOCK_TITLES.get(block_id, {}).get(language_mode)
        if not title:
            title = "未命名区块" if language_mode == ZH_HANS else "Untitled section"
        copied.update({"title": title, "content": ""})
        target_blocks.append(copied)
    target_review["blocks"] = target_blocks
    target_review["layout_schema_version"] = source_review.get("layout_schema_version", 2)


def _localized_selected_news(db: Session, source_content: dict, language_mode: str) -> list[dict]:
    selected: list[dict] = []
    for source_item in (source_content.get("sections") or {}).get("company_news") or []:
        news = db.get(NewsItem, source_item.get("news_item_id")) if source_item.get("news_item_id") else None
        metadata = dict(news.metadata_json or {}) if news else {}
        manual_same_language = bool(
            news
            and metadata.get("provider") == "MANUAL"
            and metadata.get("content_language") == language_mode
        )
        title, title_source = localized_source_text(
            language_mode=language_mode,
            en=metadata.get("title_en") or (news.title if news else None),
            zh_hans=metadata.get("title_zh_hans"),
            zh_hant=metadata.get("title_zh"),
        )
        summary, summary_source = localized_source_text(
            language_mode=language_mode,
            en=metadata.get("summary_en") or (news.summary if news else None),
            zh_hans=metadata.get("summary_zh_hans"),
            zh_hant=metadata.get("summary_zh"),
        )
        source_name, source_name_source = localized_source_text(
            language_mode=language_mode,
            en=metadata.get("source_name_en") or (news.source_name if news else None),
            zh_hans=metadata.get("source_name_zh_hans"),
            zh_hant=metadata.get("source_name_zh"),
        )
        if manual_same_language and news:
            title, summary, source_name = news.title, news.summary, news.source_name
            title_source = summary_source = source_name_source = (
                "SOURCE_ZH_HANS" if language_mode == ZH_HANS else "SOURCE_EN"
            )
        selected.append({
            **{
                key: deepcopy(value)
                for key, value in source_item.items()
                if key not in {"title", "summary", "source_name", "translation_sources"}
            },
            "title": title,
            "summary": summary,
            "source_name": source_name,
            "translation_sources": {
                "title": title_source,
                "summary": summary_source,
                "source_name": source_name_source,
            },
        })
    return selected


def create_language_variant(
    db: Session,
    source: Report,
    command: LanguageVariantCreate,
    request_id: str,
) -> Report:
    """Create an independently editable report while rebuilding the source fact lineage."""
    source_document = latest_document(db, source.id)
    if source_document.version != command.source_document_version:
        raise HTTPException(status_code=409, detail={
            "error_code": "VERSION_CONFLICT",
            "current_version": source_document.version,
        })
    if command.language_mode == source.language_mode:
        raise HTTPException(status_code=422, detail={
            "error_code": "LANGUAGE_VARIANT_SAME_AS_SOURCE",
            "message": "The requested language is already the source report language.",
        })
    existing = db.scalar(select(Report).where(
        Report.product_code == source.product_code,
        Report.report_date == source.report_date,
        Report.language_mode == command.language_mode,
        Report.revision == source.revision,
        Report.status != ReportStatus.ARCHIVED,
    ).order_by(Report.created_at.desc()))
    if existing:
        raise HTTPException(status_code=409, detail={
            "error_code": "LANGUAGE_VARIANT_EXISTS",
            "existing_report_id": existing.id,
        })

    product = resolve_product(db, source.product_code, source.report_date)
    product_name, product_name_source = localized_source_text(
        language_mode=command.language_mode,
        en=product.name_en,
        zh_hans=product.name_zh_hans,
        zh_hant=product.name_zh_hant,
    )
    report = Report(
        product_code=source.product_code,
        product_name=f"{product_name or product.ticker} ({product.ticker})",
        constituent_index_code=source.constituent_index_code,
        benchmark_instrument_code=source.benchmark_instrument_code,
        benchmark_code=source.benchmark_code,
        report_date=source.report_date,
        language_mode=command.language_mode,
        status=ReportStatus.DRAFT,
        lane=source.lane,
        revision=source.revision,
        translation_source_report_id=source.id,
        template_version=source.template_version,
    )
    db.add(report)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        existing = db.scalar(select(Report).where(
            Report.translation_source_report_id == source.id,
            Report.language_mode == command.language_mode,
        ))
        raise HTTPException(status_code=409, detail={
            "error_code": "LANGUAGE_VARIANT_EXISTS",
            "existing_report_id": existing.id if existing else None,
        }) from error

    content = initial_document(
        report.id,
        report.report_date,
        product.template_version,
        product.design_token_version,
        product.ticker,
        product.benchmark_instrument_code,
        command.language_mode,
    )
    content["translation_provenance"] = {
        "source_report_id": source.id,
        "source_document_version": source_document.version,
        "product_name": product_name_source,
        "method": "INDEPENDENT_LANGUAGE_VARIANT",
    }
    _copy_review_layout(source_document.content, content, command.language_mode)
    content["sections"]["company_news"] = _localized_selected_news(
        db, source_document.content, command.language_mode
    )

    cloned_snapshot = None
    if source.active_snapshot_id:
        source_snapshot = db.get(DataSnapshot, source.active_snapshot_id)
        if not source_snapshot:
            raise HTTPException(status_code=422, detail={"error_code": "SOURCE_SNAPSHOT_NOT_FOUND"})
        cloned_snapshot = DataSnapshot(
            report_id=report.id,
            source_snapshot_id=source_snapshot.id,
            as_of_date=source_snapshot.as_of_date,
            source_policy=source_snapshot.source_policy,
            lane=source_snapshot.lane,
            mapping_version=source_snapshot.mapping_version,
            status=source_snapshot.status,
            checksum=source_snapshot.checksum,
            payload=deepcopy(source_snapshot.payload),
            quality_results=deepcopy(source_snapshot.quality_results),
        )
        db.add(cloned_snapshot)
        db.flush()
        dataset_id_map: dict[str, str] = {}
        for item in db.scalars(select(SnapshotDataset).where(
            SnapshotDataset.snapshot_id == source_snapshot.id
        )):
            lineage = deepcopy(item.lineage or {})
            lineage.update({
                "language_variant_source_snapshot_id": source_snapshot.id,
                "language_variant_source_dataset_id": item.id,
                "source_checksum": item.checksum,
            })
            cloned = SnapshotDataset(
                snapshot_id=cloned_snapshot.id,
                dataset_type=item.dataset_type,
                source_type=item.source_type,
                source_object=item.source_object,
                row_count=item.row_count,
                coverage=item.coverage,
                checksum=item.checksum,
                parser_version=item.parser_version,
                mapping_version=item.mapping_version,
                validation_results=deepcopy(item.validation_results),
                lineage=lineage,
            )
            db.add(cloned)
            db.flush()
            dataset_id_map[item.id] = cloned.id
        report.active_snapshot_id = cloned_snapshot.id
        report.lane = cloned_snapshot.lane
        content = bind_snapshot(content, cloned_snapshot.payload, lane=cloned_snapshot.lane)
        content["snapshot_id"] = cloned_snapshot.id

    document = ReportDocument(
        report_id=report.id,
        version=1,
        snapshot_id=cloned_snapshot.id if cloned_snapshot else None,
        template_version=report.template_version,
        language_mode=report.language_mode,
        content=content,
        checksum=checksum(content),
    )
    db.add(document)

    source_selections = list(db.scalars(select(ReportNewsSelection).where(
        ReportNewsSelection.report_id == source.id
    ).order_by(ReportNewsSelection.position)))
    for selection in source_selections:
        db.add(ReportNewsSelection(
            report_id=report.id,
            news_item_id=selection.news_item_id,
            position=selection.position,
        ))
    for candidate in db.scalars(select(ReportNewsCandidate).where(
        ReportNewsCandidate.report_id == source.id
    )):
        db.add(ReportNewsCandidate(
            report_id=report.id,
            news_item_id=candidate.news_item_id,
            provider=candidate.provider,
            match_status=candidate.match_status,
            match_evidence={
                **deepcopy(candidate.match_evidence or {}),
                "language_variant_source_candidate_id": candidate.id,
            },
        ))
    audit(db, "report.language_variant_created", "report", report.id, request_id, {
        "source_report_id": source.id,
        "source_document_version": source_document.version,
        "source_snapshot_id": source.active_snapshot_id,
        "target_snapshot_id": cloned_snapshot.id if cloned_snapshot else None,
        "language_mode": command.language_mode,
    })
    db.commit()
    db.refresh(report)

    if cloned_snapshot and cloned_snapshot.status.value == "VALID":
        # Import locally to preserve the service-layer dependency direction.
        from .calculations import run_calculation

        run_calculation(db, report, request_id)
        db.refresh(report)
    return report


def get_report(db: Session, report_id: str) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail={"error_code": "REPORT_NOT_FOUND", "message": "Report not found."})
    return report


def delete_report(db: Session, report: Report, expected_version: int, request_id: str) -> None:
    """Soft-delete a report while preserving its regulated lineage and artifacts."""
    if report.status == ReportStatus.ARCHIVED:
        return
    if report.version != expected_version:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "VERSION_CONFLICT", "current_version": report.version},
        )

    previous_status = report.status.value
    report.status = ReportStatus.ARCHIVED
    report.version += 1
    audit(db, "report.deleted", "report", report.id, request_id, {
        "deletion_mode": "SOFT_DELETE",
        "previous_status": previous_status,
        "retained_for_audit": True,
    })
    db.commit()


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
    # The review API still exposes the testing lane, and every artifact carries the watermark and
    # the TESTING- filename prefix.
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
    checks.extend(chinese_content_warnings(document.content))
    return checks


def finalize(db: Session, report: Report, expected_version: int, request_id: str) -> Report:
    if report.status == ReportStatus.FINALIZED:
        return report
    document = latest_document(db, report.id)
    if document.version != expected_version:
        raise HTTPException(status_code=409, detail={"error_code": "VERSION_CONFLICT", "current_version": document.version})
    advisory_failures = [
        item for item in release_gate_checks(db, report, document)
        if item.get("severity") == "BLOCKING" and item.get("status") != "PASSED"
    ]

    report.status = ReportStatus.READY_TO_FINALIZE
    report.finalized_document_version = document.version
    report.status = ReportStatus.FINALIZED
    report.version += 1
    audit(db, "report.finalized", "report", report.id, request_id, {
        "document_version": document.version,
        "advisory_check_ids": [str(item.get("check_id") or "QUALITY_CHECK") for item in advisory_failures],
    })
    db.commit()
    db.refresh(report)
    return report
