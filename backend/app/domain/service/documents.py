"""Report document versions.

Every edit appends a new :class:`ReportDocument`; nothing is written in place. Kept below
``snapshots`` in the dependency order because binding a snapshot into a document needs the
latest document, but no document operation needs a snapshot operation.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..document import (
    DocumentValidationError,
    checksum,
    has_substantive_review_blocks,
    validate_document_content,
)
from ..localization import is_chinese, is_zh_hant, month_name, simplified_to_traditional
from ..metrics.final_analytics import calculate_snapshot
from ..models import DataSnapshot, Report, ReportDocument, ReportStatus
from ..page_one_presentation import PageOnePresentationError, page_one_presentation
from .audit import audit
from .catalog import resolve_product
from .lifecycle import ensure_report_editable


def latest_document(db: Session, report_id: str, *, for_update: bool = False) -> ReportDocument:
    query = select(ReportDocument).where(ReportDocument.report_id == report_id).order_by(ReportDocument.version.desc()).limit(1)
    document = db.scalar(query.with_for_update().execution_options(populate_existing=True) if for_update else query)
    if not document:
        raise HTTPException(status_code=404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": "Report document not found."})
    return document


def lock_report(db: Session, report: Report) -> None:
    db.flush()
    db.refresh(report, with_for_update=True)


def document_content_for_read(report: Report, document: ReportDocument) -> dict[str, Any]:
    """Return an in-memory v4 adapter for editable legacy documents.

    Finalized and archived documents keep their exact locked layout.  No ORM JSON value is
    mutated: callers receive a deep copy even when no adaptation is needed.
    """

    content = deepcopy(document.content)
    if (
        document.template_version in {"3033-v1", "3033-v2", "3033-v3"}
        and report.status not in {ReportStatus.FINALIZED, ReportStatus.ARCHIVED}
    ):
        # v1 has no presentation-aware renderer, so never expose the invalid hybrid
        # ``template_version=v1`` + ``presentation.schema_version=2``.  This is still an
        # in-memory read adapter; persistence and the report identity change on first save.
        return page_one_presentation.upgrade_document_to_v4(
            content,
            stamp_template=document.template_version == "3033-v1",
        )
    return page_one_presentation.adapt_document(content) if document.template_version == "3033-v4" else content


def canonicalize_document_content(
    report: Report,
    product: Any,
    content: dict[str, Any],
    *,
    current_content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Purely restamp, reconcile and validate submitted document content.

    Persistence and audit stay with :func:`update_document`; draft preview calls this same seam
    without creating a version. Editable v1-v3 reports are upgraded to v4 in the returned value,
    allowing the caller to persist report/document/template identities atomically afterwards.
    """

    target_template_version = (
        "3033-v4"
        if report.template_version in {"3033-v1", "3033-v2", "3033-v3", "3033-v4"}
        else report.template_version
    )
    canonical = page_one_presentation.reconcile_submission(
        deepcopy(content), deepcopy(current_content) if current_content is not None else None
    )
    canonical.update({
        "report_id": report.id,
        "report_date": report.report_date.isoformat(),
        "month_name": month_name(report.report_date, report.language_mode),
        "product_ticker": product.ticker,
        "benchmark_name": product.benchmark_instrument_name or product.benchmark_instrument_code,
        "template_version": target_template_version,
        "design_token_version": (
            "3033-v4" if target_template_version == "3033-v4" else product.design_token_version
        ),
        "language_mode": report.language_mode,
        "snapshot_id": report.active_snapshot_id,
        # Restamped canonically: the lane belongs to the data, so an editor cannot drop it from the
        # document JSON to strip the TESTING watermark off the rendered output.
        "lane": report.lane,
    })
    return validate_document_content(canonical)


def _validation_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, PageOnePresentationError):
        return HTTPException(status_code=422, detail={
            "error_code": error.error_code,
            "field": error.field,
            "entity_id": error.entity_id,
            "message": str(error),
            "severity": "BLOCKING",
            "fix_hint": error.fix_hint,
        })
    if isinstance(error, DocumentValidationError):
        return HTTPException(status_code=422, detail={
            "error_code": error.error_code,
            "field": error.field,
            "entity_id": error.entity_id,
            "message": str(error),
            "severity": "BLOCKING",
            "fix_hint": error.fix_hint,
        })
    return HTTPException(status_code=422, detail={
        "error_code": "REVIEW_LAYOUT_INVALID",
        "message": str(error),
        "severity": "BLOCKING",
        "fix_hint": "Keep every Review block inside the 12-column canvas without overlap.",
    })


def preview_document_content(
    db: Session,
    report: Report,
    *,
    expected_version: int | None = None,
    content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return canonical preview content without writing a version or audit event."""

    current = latest_document(db, report.id)
    if content is None:
        return document_content_for_read(report, current)
    ensure_report_editable(report)
    # Preview does not mutate the append-only document. The supplied version identifies the
    # editor's base for compatibility with the save payload, but a newer saved version must not
    # prevent the user from rendering and recovering their unsaved draft. update_document keeps
    # the optimistic-lock check for the actual write boundary.
    _ = expected_version
    product = resolve_product(db, report.product_code, report.report_date)
    try:
        return canonicalize_document_content(
            report, product, content, current_content=current.content
        )
    except (DocumentValidationError, PageOnePresentationError, ValueError) as error:
        raise _validation_http_exception(error) from error


def update_document(db: Session, report: Report, expected_version: int, content: dict, request_id: str) -> ReportDocument:
    lock_report(db, report)
    ensure_report_editable(report)
    current = latest_document(db, report.id, for_update=True)
    if current.version != expected_version:
        raise HTTPException(status_code=409, detail={
            "error_code": "VERSION_CONFLICT",
            "message": "Document was changed by another editor.",
            "current_version": current.version,
            "current_checksum": current.checksum,
        })
    product = resolve_product(db, report.product_code, report.report_date)
    try:
        content = canonicalize_document_content(
            report, product, content, current_content=current.content
        )
    except (DocumentValidationError, PageOnePresentationError, ValueError) as error:
        raise _validation_http_exception(error) from error
    previous_template_version = report.template_version
    report.template_version = str(content["template_version"])
    document = ReportDocument(
        report_id=report.id,
        version=current.version + 1,
        snapshot_id=report.active_snapshot_id,
        template_version=str(content["template_version"]),
        language_mode=report.language_mode,
        content=content,
        checksum=checksum(content),
    )
    db.add(document)
    if report.status in {ReportStatus.DATA_READY, ReportStatus.READY_TO_FINALIZE, ReportStatus.REVIEW}:
        report.status = ReportStatus.EDITING
    report.version += 1
    audit(db, "document.updated", "report", report.id, request_id, {
        "document_version": document.version,
        **(
            {"template_upgraded_from": previous_template_version, "template_upgraded_to": report.template_version}
            if previous_template_version != report.template_version
            else {}
        ),
    })
    db.commit()
    db.refresh(document)
    return document


def ai_assisted_draft(db: Session, report: Report, expected_version: int, user_prompt: str, request_id: str) -> ReportDocument:
    ensure_report_editable(report)
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
    if is_chinese(report.language_mode):
        summary = (
            f"{month}期间，{report.benchmark_code} 成份股集合包含 {metrics['constituent_count']} 只成份股，"
            f"覆盖 {metrics['sector_count']} 个已映射行业。个股表现分化；一个月表现最佳的证券代码为 "
            f"{metrics['top_security_code']}，表现最弱的证券代码为 {metrics['bottom_security_code']}。"
        )
        drivers = [{"title": "成份股表现分化", "body": "发布前请复核已绑定的最佳及最弱成份股数据与已选公司新闻。"}]
        monitor = [{"title": "盈利兑现与流动性", "body": "关注公司指引、外部流动性环境及盈利可持续增长的证据。"}]
        outlook = user_prompt or "请使用已批准的投资评论完成展望。"
        if is_zh_hant(report.language_mode):
            summary = simplified_to_traditional(summary)
            drivers = [{key: simplified_to_traditional(value) for key, value in item.items()} for item in drivers]
            monitor = [{key: simplified_to_traditional(value) for key, value in item.items()} for item in monitor]
            outlook = simplified_to_traditional(outlook)
    else:
        summary = (
            f"During {month}, the {report.benchmark_code} constituent set contained {metrics['constituent_count']} constituents across "
            f"{metrics['sector_count']} mapped sectors. Performance remained differentiated; the strongest one-month "
            f"constituent was security {metrics['top_security_code']}, while security {metrics['bottom_security_code']} was the weakest."
        )
        drivers = [{"title": "Differentiated constituent performance", "body": "Review the bound Top and Bottom Performers data and selected company news before publication."}]
        monitor = [{"title": "Earnings delivery and liquidity", "body": "Monitor company guidance, external liquidity conditions, and evidence of sustainable earnings growth."}]
        outlook = user_prompt or "Complete the outlook using approved investment commentary."
    review = content["sections"]["month_in_review"]
    replace_placeholder_blocks = (
        content.get("template_version") in {"3033-v3", "3033-v4"}
        and not has_substantive_review_blocks(review)
    )
    review["summary"] = summary
    review["drivers"] = drivers
    review["monitor"] = monitor
    review["outlook"] = outlook
    if replace_placeholder_blocks:
        review.pop("blocks", None)
        review.pop("layout_schema_version", None)
        content = page_one_presentation.adapt_document(content)
    content["ai_provenance"] = {
        "provider": "deterministic-template",
        "model": "no-external-model",
        "prompt_version": "in-review-v1",
        "metric_bindings": ["constituent_count", "sector_count", "top_security_code", "bottom_security_code"],
    }
    return update_document(db, report, current.version, content, request_id)
