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
from app.core.security import current_principal
from ..document import (
    bind_snapshot,
    checksum,
    initial_document,
    review_plain_text,
    validate_document_content,
)
from ..localization import (
    ZH_HANS,
    ZH_HANT,
    chinese_content_warnings,
    localized_source_text,
    simplified_to_traditional,
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
from ..page_one_presentation import PageOneLayoutOverflowError, page_one_presentation
from ..schemas import LanguageVariantCreate, LanguageVariantSync, ReportCreate
from .lifecycle import ensure_report_editable, ensure_report_not_archived
from .audit import audit
from .catalog import resolve_product
from .documents import latest_document, update_document
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
    "summary": {"EN": "Monthly Review", ZH_HANS: "月度回顾", ZH_HANT: "月度回顧"},
    "drivers": {"EN": "Key Drivers", ZH_HANS: "主要驱动因素", ZH_HANT: "主要驅動因素"},
    "monitor": {"EN": "Key Areas to Monitor", ZH_HANS: "重点关注领域", ZH_HANT: "重點關注領域"},
    "outlook": {"EN": "Outlook", ZH_HANS: "展望", ZH_HANT: "展望"},
}
_CHINESE_LANGUAGE_MODES = {ZH_HANS, ZH_HANT}
_HTML_TAG = re.compile(r"(<[^>]+>)")


def _convert_chinese_text(value: object, source_language: str, target_language: str, *, html: bool = False) -> str:
    text_value = str(value or "")
    if source_language == target_language or {source_language, target_language} != _CHINESE_LANGUAGE_MODES:
        return text_value
    convert = traditional_to_simplified if target_language == ZH_HANS else simplified_to_traditional
    if not html:
        return convert(text_value)
    return "".join(part if part.startswith("<") else convert(part) for part in _HTML_TAG.split(text_value))


def _merge_converted_text(
    *,
    path: str,
    source_value: object,
    target_value: object,
    source: Report,
    target: Report,
    source_document_version: int,
    fields: dict[str, dict],
    force: bool,
    html: bool = False,
) -> str:
    source_text = str(source_value or "")
    target_text = str(target_value or "")
    previous = fields.get(path) if isinstance(fields.get(path), dict) else None
    target_is_generated = bool(previous and checksum(target_text) == previous.get("target_checksum"))
    if not (force or not target_text.strip() or target_is_generated):
        fields.pop(path, None)
        return target_text
    converted = _convert_chinese_text(
        source_text,
        source.language_mode,
        target.language_mode,
        html=html,
    )
    fields[path] = {
        "method": "OPENCC_T2S" if target.language_mode == ZH_HANS else "OPENCC_S2T",
        "source_report_id": source.id,
        "source_document_version": source_document_version,
        "source_checksum": checksum(source_text),
        "target_checksum": checksum(converted),
    }
    return converted


def _sync_chinese_editorial(
    *,
    source: Report,
    target: Report,
    source_document: ReportDocument,
    target_content: dict,
    source_news_overrides: dict[str, tuple[str | None, str | None]],
    target_news_overrides: dict[str, tuple[str | None, str | None]],
    force: bool = False,
) -> dict[str, tuple[str | None, str | None]]:
    """Convert Chinese-authored editorial while preserving target-side manual edits."""
    if (
        source.language_mode == target.language_mode
        or source.language_mode not in _CHINESE_LANGUAGE_MODES
        or target.language_mode not in _CHINESE_LANGUAGE_MODES
    ):
        return target_news_overrides

    provenance = deepcopy(target_content.get("translation_provenance") or {})
    fields = deepcopy(provenance.get("fields") or {})

    def merge(path: str, source_value: object, target_value: object, *, html: bool = False) -> str:
        return _merge_converted_text(
            path=path,
            source_value=source_value,
            target_value=target_value,
            source=source,
            target=target,
            source_document_version=source_document.version,
            fields=fields,
            force=force,
            html=html,
        )

    source_sections = source_document.content.get("sections") or {}
    target_sections = target_content.get("sections") or {}
    source_review = source_sections.get("month_in_review") or {}
    target_review = target_sections.get("month_in_review") or {}
    for field in ("title", "display_title", "summary", "outlook"):
        if field in source_review:
            target_review[field] = merge(
                f"sections.month_in_review.{field}",
                source_review.get(field),
                target_review.get(field),
            )
    source_blocks = {
        str(item.get("block_id") or ""): item
        for item in source_review.get("blocks") or []
        if isinstance(item, dict) and item.get("block_id")
    }
    for block in target_review.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or "")
        source_block = source_blocks.get(block_id)
        if not source_block:
            continue
        for field in ("title", "content"):
            block[field] = merge(
                f"sections.month_in_review.blocks.{block_id}.{field}",
                source_block.get(field),
                block.get(field),
                html=field == "content",
            )
    for collection in ("drivers", "monitor"):
        source_items = source_review.get(collection) or []
        target_items = target_review.get(collection) or []
        if not isinstance(source_items, list) or not isinstance(target_items, list):
            continue
        while len(target_items) < len(source_items):
            target_items.append({})
        for index, source_item in enumerate(source_items):
            if not isinstance(source_item, dict) or not isinstance(target_items[index], dict):
                continue
            for field in ("title", "body"):
                target_items[index][field] = merge(
                    f"sections.month_in_review.{collection}.{index}.{field}",
                    source_item.get(field),
                    target_items[index].get(field),
                )
        target_review[collection] = target_items[:len(source_items)]
    target_sections["month_in_review"] = target_review

    source_footnotes = source_sections.get("footnotes") or {}
    target_footnotes = target_sections.get("footnotes") or {}
    for key, source_value in source_footnotes.items():
        target_footnotes[key] = merge(
            f"sections.footnotes.{key}", source_value, target_footnotes.get(key)
        )
    target_sections["footnotes"] = target_footnotes

    source_terms = source_document.content.get("terminology_overrides") or {}
    target_terms = target_content.get("terminology_overrides") or {}
    for key in ("product_name", "benchmark_name"):
        if key in source_terms:
            target_terms[key] = merge(
                f"terminology_overrides.{key}", source_terms.get(key), target_terms.get(key)
            )
    for collection in ("securities", "industries"):
        source_values = source_terms.get(collection) or {}
        target_values = target_terms.get(collection) or {}
        for key, source_value in source_values.items():
            target_values[key] = merge(
                f"terminology_overrides.{collection}.{key}", source_value, target_values.get(key)
            )
        target_terms[collection] = target_values
    target_content["terminology_overrides"] = target_terms
    target_content["sections"] = target_sections

    converted_news_overrides = dict(target_news_overrides)
    source_news_items = {
        str(item.get("news_item_id") or ""): item
        for item in source_sections.get("company_news") or []
        if isinstance(item, dict) and item.get("news_item_id")
    }
    for news_item_id, source_values in source_news_overrides.items():
        target_values = converted_news_overrides.get(news_item_id, (None, None))
        source_news_item = source_news_items.get(news_item_id) or {}
        is_manual_news = source_news_item.get("provider") == "MANUAL"
        converted: list[str | None] = []
        for index, field in enumerate(("title_override", "summary_override")):
            source_value = source_values[index]
            if source_value is None and is_manual_news:
                source_value = source_news_item.get("title" if index == 0 else "summary")
            if source_value is None:
                converted.append(target_values[index])
                continue
            converted.append(merge(
                f"sections.company_news.{news_item_id}.{field}",
                source_value,
                target_values[index],
            ))
        converted_news_overrides[news_item_id] = (converted[0], converted[1])

    target_content["translation_provenance"] = {
        **provenance,
        "source_report_id": source.id,
        "source_document_version": source_document.version,
        "method": "CHINESE_VARIANT_SYNC",
        "fields": fields,
    }
    return converted_news_overrides


def _copy_review_layout(source: dict, target: dict, language_mode: str) -> None:
    source_review = (source.get("sections") or {}).get("month_in_review") or {}
    blocks = source_review.get("blocks")
    source_presentation = source.get("presentation")
    if isinstance(source_presentation, dict):
        target["presentation"] = deepcopy(source_presentation)
    if not isinstance(blocks, list):
        return
    target_review = target["sections"]["month_in_review"]
    existing_blocks = {
        str(block.get("block_id") or ""): block
        for block in target_review.get("blocks") or []
        if isinstance(block, dict)
    }
    target_blocks: list[dict] = []
    for block in blocks:
        copied = {
            key: deepcopy(value)
            for key, value in block.items()
            if key not in {"title", "content"}
        }
        block_id = str(block.get("block_id") or "")
        existing = existing_blocks.get(block_id) or {}
        title = existing.get("title") or _REVIEW_BLOCK_TITLES.get(block_id, {}).get(language_mode)
        if not title:
            title = "未命名區塊" if language_mode == ZH_HANT else "未命名区块" if language_mode == ZH_HANS else "Untitled section"
        copied.update({"title": title, "content": existing.get("content", "")})
        target_blocks.append(copied)
    if "EN" in {source.get("language_mode", "EN"), language_mode}:
        source_ids = {str(block.get("block_id")) for block in blocks}
        for block_id, existing in existing_blocks.items():
            if block_id in source_ids:
                continue
            retained = deepcopy(existing)
            retained["y"] = max((block["y"] + block["h"] for block in target_blocks), default=0)
            target_blocks.append(retained)
    target_review["blocks"] = target_blocks
    target_review["layout_schema_version"] = source_review.get("layout_schema_version", 2)


def _localized_selected_news(
    db: Session,
    source_content: dict,
    language_mode: str,
    overrides: dict[str, tuple[str | None, str | None]] | None = None,
) -> list[dict]:
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
            title_source = summary_source = source_name_source = {
                ZH_HANS: "SOURCE_ZH_HANS",
                ZH_HANT: "SOURCE_ZH_HANT",
            }.get(language_mode, "SOURCE_EN")
        elif (
            news
            and metadata.get("provider") == "MANUAL"
            and metadata.get("content_language") in _CHINESE_LANGUAGE_MODES
            and language_mode in _CHINESE_LANGUAGE_MODES
        ):
            source_language = str(metadata.get("content_language"))
            title = _convert_chinese_text(news.title, source_language, language_mode)
            summary = _convert_chinese_text(news.summary, source_language, language_mode)
            source_name = _convert_chinese_text(news.source_name, source_language, language_mode)
            conversion_source = "OPENCC_T2S" if language_mode == ZH_HANS else "OPENCC_S2T"
            title_source = summary_source = source_name_source = conversion_source
        title_override, summary_override = (overrides or {}).get(str(source_item.get("news_item_id") or ""), (None, None))
        selected.append({
            **{
                key: deepcopy(value)
                for key, value in source_item.items()
                if key not in {"title", "summary", "source_name", "translation_sources"}
            },
            "title": title_override if title_override is not None else title,
            "summary": summary_override if summary_override is not None else summary,
            "source_name": source_name,
            "translation_sources": {
                "title": "MANUAL_OVERRIDE" if title_override is not None else title_source,
                "summary": "MANUAL_OVERRIDE" if summary_override is not None else summary_source,
                "source_name": source_name_source,
            },
        })
    return selected


def _clone_language_snapshot(db: Session, source_snapshot: DataSnapshot, report: Report) -> DataSnapshot:
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
    for item in db.scalars(select(SnapshotDataset).where(
        SnapshotDataset.snapshot_id == source_snapshot.id
    )):
        lineage = deepcopy(item.lineage or {})
        lineage.update({
            "language_variant_source_snapshot_id": source_snapshot.id,
            "language_variant_source_dataset_id": item.id,
            "source_checksum": item.checksum,
        })
        db.add(SnapshotDataset(
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
        ))
    report.active_snapshot_id = cloned_snapshot.id
    report.lane = cloned_snapshot.lane
    return cloned_snapshot


def _sync_news_selections(db: Session, source: Report, target: Report) -> dict[str, tuple[str | None, str | None]]:
    source_selections = list(db.scalars(select(ReportNewsSelection).where(
        ReportNewsSelection.report_id == source.id
    ).order_by(ReportNewsSelection.position)))
    target_selections = list(db.scalars(select(ReportNewsSelection).where(
        ReportNewsSelection.report_id == target.id
    ).order_by(ReportNewsSelection.position)))
    target_overrides = {
        item.news_item_id: (item.title_override, item.summary_override)
        for item in target_selections
    }
    source_order = [(item.news_item_id, item.position) for item in source_selections]
    target_order = [(item.news_item_id, item.position) for item in target_selections]
    if source_order != target_order:
        db.query(ReportNewsSelection).filter(ReportNewsSelection.report_id == target.id).delete()
        for selection in source_selections:
            title_override, summary_override = target_overrides.get(selection.news_item_id, (None, None))
            db.add(ReportNewsSelection(
                report_id=target.id,
                news_item_id=selection.news_item_id,
                position=selection.position,
                title_override=title_override,
                summary_override=summary_override,
            ))
    existing_candidates = set(db.scalars(select(ReportNewsCandidate.news_item_id).where(
        ReportNewsCandidate.report_id == target.id
    )))
    for candidate in db.scalars(select(ReportNewsCandidate).where(
        ReportNewsCandidate.report_id == source.id
    )):
        if candidate.news_item_id in existing_candidates:
            continue
        db.add(ReportNewsCandidate(
            report_id=target.id,
            news_item_id=candidate.news_item_id,
            provider=candidate.provider,
            match_status=candidate.match_status,
            match_evidence={
                **deepcopy(candidate.match_evidence or {}),
                "language_variant_source_candidate_id": candidate.id,
            },
        ))
    return target_overrides


def _news_selection_overrides(
    db: Session,
    report_id: str,
) -> dict[str, tuple[str | None, str | None]]:
    return {
        str(item.news_item_id): (item.title_override, item.summary_override)
        for item in db.scalars(select(ReportNewsSelection).where(
            ReportNewsSelection.report_id == report_id
        ))
    }


def _apply_news_selection_overrides(
    db: Session,
    report_id: str,
    overrides: dict[str, tuple[str | None, str | None]],
) -> None:
    db.flush()
    for item in db.scalars(select(ReportNewsSelection).where(
        ReportNewsSelection.report_id == report_id
    )):
        title_override, summary_override = overrides.get(
            str(item.news_item_id),
            (item.title_override, item.summary_override),
        )
        item.title_override = title_override
        item.summary_override = summary_override


def create_language_variant(
    db: Session,
    source: Report,
    command: LanguageVariantCreate,
    request_id: str,
) -> Report:
    """Create an independently editable report while rebuilding the source fact lineage."""
    ensure_report_not_archived(source)
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
    target_template_version = source_document.template_version or source.template_version
    target_design_token_version = str(
        source_document.content.get("design_token_version") or target_template_version
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
        template_version=target_template_version,
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
        target_template_version,
        target_design_token_version,
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

    source_selections = list(db.scalars(select(ReportNewsSelection).where(
        ReportNewsSelection.report_id == source.id
    ).order_by(ReportNewsSelection.position)))
    target_selection_rows: list[ReportNewsSelection] = []
    for selection in source_selections:
        target_selection = ReportNewsSelection(
            report_id=report.id,
            news_item_id=selection.news_item_id,
            position=selection.position,
        )
        db.add(target_selection)
        target_selection_rows.append(target_selection)
    source_overrides = {
        str(item.news_item_id): (item.title_override, item.summary_override)
        for item in source_selections
    }
    converted_overrides = _sync_chinese_editorial(
        source=source,
        target=report,
        source_document=source_document,
        target_content=content,
        source_news_overrides=source_overrides,
        target_news_overrides={},
        force=True,
    )
    for selection in target_selection_rows:
        selection.title_override, selection.summary_override = converted_overrides.get(
            str(selection.news_item_id), (None, None)
        )
    content["sections"]["company_news"] = _localized_selected_news(
        db, source_document.content, command.language_mode, converted_overrides
    )

    cloned_snapshot = None
    if source.active_snapshot_id:
        source_snapshot = db.get(DataSnapshot, source.active_snapshot_id)
        if not source_snapshot:
            raise HTTPException(status_code=422, detail={"error_code": "SOURCE_SNAPSHOT_NOT_FOUND"})
        cloned_snapshot = _clone_language_snapshot(db, source_snapshot, report)
        content = bind_snapshot(content, cloned_snapshot.payload, lane=cloned_snapshot.lane)
        content["snapshot_id"] = cloned_snapshot.id

    content = page_one_presentation.retarget_footnote_styles(content)
    if content.get("template_version") == "3033-v3":
        content = validate_document_content(content)

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

        # Calculation rebuilds deterministic sections. Reapply Chinese editorial
        # conversion afterwards so source-authored prose and its field provenance
        # remain part of the latest document version.
        calculated_document = latest_document(db, report.id)
        calculated_content = deepcopy(calculated_document.content)
        current_overrides = _news_selection_overrides(db, report.id)
        converted_overrides = _sync_chinese_editorial(
            source=source,
            target=report,
            source_document=source_document,
            target_content=calculated_content,
            source_news_overrides=source_overrides,
            target_news_overrides=current_overrides,
            force=True,
        )
        calculated_content = page_one_presentation.retarget_footnote_styles(
            calculated_content
        )
        _apply_news_selection_overrides(db, report.id, converted_overrides)
        calculated_content["sections"]["company_news"] = _localized_selected_news(
            db, source_document.content, report.language_mode, converted_overrides
        )
        if checksum(calculated_content) != calculated_document.checksum:
            update_document(
                db,
                report,
                calculated_document.version,
                calculated_content,
                request_id,
            )
        else:
            db.commit()
        db.refresh(report)
    return report


def sync_language_variant(
    db: Session,
    source: Report,
    target: Report,
    command: LanguageVariantSync,
    request_id: str,
) -> Report:
    """Synchronize language-neutral module choices while preserving translated prose."""
    ensure_report_not_archived(source)
    ensure_report_editable(target)
    source_document = latest_document(db, source.id)
    target_document = latest_document(db, target.id)
    if source_document.version != command.source_document_version:
        raise HTTPException(status_code=409, detail={
            "error_code": "VERSION_CONFLICT",
            "report_id": source.id,
            "current_version": source_document.version,
        })
    if target_document.version != command.target_document_version:
        raise HTTPException(status_code=409, detail={
            "error_code": "VERSION_CONFLICT",
            "report_id": target.id,
            "current_version": target_document.version,
        })
    if source.id == target.id or source.language_mode == target.language_mode:
        raise HTTPException(status_code=422, detail={
            "error_code": "LANGUAGE_VARIANT_PAIR_REQUIRED",
            "message": "Source and target must be different language reports.",
        })
    if (
        source.product_code != target.product_code
        or source.report_date != target.report_date
        or source.revision != target.revision
    ):
        raise HTTPException(status_code=422, detail={
            "error_code": "LANGUAGE_VARIANT_CONTEXT_MISMATCH",
            "message": "Language variants must have the same product, report month and revision.",
        })
    snapshot_changed = False
    if source.active_snapshot_id:
        source_snapshot = db.get(DataSnapshot, source.active_snapshot_id)
        if not source_snapshot:
            raise HTTPException(status_code=422, detail={"error_code": "SOURCE_SNAPSHOT_NOT_FOUND"})
        target_snapshot = db.get(DataSnapshot, target.active_snapshot_id) if target.active_snapshot_id else None
        if (
            not target_snapshot
            or target_snapshot.checksum != source_snapshot.checksum
            or target_snapshot.payload != source_snapshot.payload
        ):
            cloned_snapshot = _clone_language_snapshot(db, source_snapshot, target)
            target.status = ReportStatus.DATA_READY if cloned_snapshot.status.value == "VALID" else ReportStatus.DRAFT
            db.commit()
            db.refresh(target)
            snapshot_changed = True
            if cloned_snapshot.status.value == "VALID":
                from .calculations import run_calculation

                run_calculation(db, target, request_id)
                db.refresh(target)

    target_document = latest_document(db, target.id)
    content = deepcopy(target_document.content)
    if snapshot_changed and target.active_snapshot_id and target_document.snapshot_id != target.active_snapshot_id:
        target_snapshot = db.get(DataSnapshot, target.active_snapshot_id)
        if target_snapshot:
            content = bind_snapshot(content, target_snapshot.payload, lane=target_snapshot.lane)
            content["snapshot_id"] = target_snapshot.id
    _copy_review_layout(source_document.content, content, target.language_mode)

    source_news = (source_document.content.get("sections") or {}).get("company_news") or []
    source_news_by_id = {
        str(item.get("news_item_id")): item
        for item in source_news
        if isinstance(item, dict) and item.get("news_item_id")
    }
    source_selections = list(db.scalars(select(ReportNewsSelection).where(
        ReportNewsSelection.report_id == source.id
    ).order_by(ReportNewsSelection.position)))
    localized_source = deepcopy(source_document.content)
    localized_source["sections"] = dict(localized_source.get("sections") or {})
    localized_source["sections"]["company_news"] = [
        deepcopy(source_news_by_id.get(item.news_item_id, {"news_item_id": item.news_item_id}))
        for item in source_selections
    ]
    target_overrides = _sync_news_selections(db, source, target)
    source_overrides = {
        str(item.news_item_id): (item.title_override, item.summary_override)
        for item in source_selections
    }
    target_overrides = _sync_chinese_editorial(
        source=source,
        target=target,
        source_document=source_document,
        target_content=content,
        source_news_overrides=source_overrides,
        target_news_overrides=target_overrides,
    )
    _apply_news_selection_overrides(db, target.id, target_overrides)
    content["sections"]["company_news"] = _localized_selected_news(
        db, localized_source, target.language_mode, target_overrides
    )

    if source_document.content.get("next_rebalancing_date_source") == "MANUAL":
        content["next_rebalancing_date"] = source_document.content.get("next_rebalancing_date")
        content["next_rebalancing_date_source"] = "MANUAL"

    content = page_one_presentation.retarget_footnote_styles(content)

    if checksum(content) != target_document.checksum:
        update_document(db, target, target_document.version, content, request_id)
    else:
        db.commit()
    audit(db, "report.language_variant_synced", "report", target.id, request_id, {
        "source_report_id": source.id,
        "source_document_version": source_document.version,
        "target_document_version": latest_document(db, target.id).version,
        "snapshot_changed": snapshot_changed,
    })
    db.commit()
    db.refresh(target)
    return target


def get_report(db: Session, report_id: str) -> Report:
    report = db.get(Report, report_id)
    # Out-of-scope reports answer 404, not 403: a distinguishable 403 would let a caller enumerate
    # which funds exist by probing identifiers. Every route reaches a report through here, so the
    # check cannot be forgotten on a new endpoint.
    caller = current_principal()
    if not report or (caller is not None and not caller.may_access_product(report.product_code)):
        raise HTTPException(status_code=404, detail={"error_code": "REPORT_NOT_FOUND", "message": "Report not found."})
    return report


def visible_product_codes() -> frozenset[str] | None:
    """Product codes the current caller may list, or ``None`` when unrestricted."""
    caller = current_principal()
    if caller is None or caller.is_unrestricted:
        return None
    return caller.product_scope


def delete_report(db: Session, report: Report, expected_version: int, request_id: str) -> None:
    """Soft-delete a report while preserving its regulated lineage and artifacts."""
    from .documents import lock_report

    lock_report(db, report)
    ensure_report_not_archived(report)
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
    ensure_report_not_archived(source)
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


def _review_editorial_text(review: object) -> str:
    """Return authored Review prose without layout coordinates or style-role numbers."""

    if not isinstance(review, dict):
        return ""
    blocks = review.get("blocks")
    if isinstance(blocks, list):
        return " ".join(
            review_plain_text(str(block.get("content") or ""))
            for block in blocks
            if isinstance(block, dict)
        )
    prose: list[str] = [str(review.get("summary") or ""), str(review.get("outlook") or "")]
    for collection in ("drivers", "monitor"):
        for item in review.get(collection) or []:
            if isinstance(item, dict):
                prose.extend((str(item.get("title") or ""), str(item.get("body") or "")))
    return " ".join(prose)


def ai_number_check(db: Session, report: Report, document: ReportDocument) -> dict:
    from ..editorial_translation import translated_review_text

    translated = translated_review_text(document.content)
    provenance = document.content.get("ai_provenance")
    if not provenance and not translated:
        return {
            "check_id": "QC-008",
            "severity": "BLOCKING",
            "status": "PASSED",
            "actual": {"checked": False, "unmatched": []},
            "threshold": "Every AI-authored number matches a bound metric or selected news citation.",
            "fix_hint": "",
        }
    review = document.content.get("sections", {}).get("month_in_review", {})
    actual_tokens = _numeric_tokens(
        _review_editorial_text(review) if provenance else " ".join(translated)
    )
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
    from .documents import lock_report
    from app.rendering.artifacts import assert_page_one_layout_fits
    from app.rendering.disclaimer import DisclaimerResourceError

    lock_report(db, report)
    ensure_report_not_archived(report)
    if report.status == ReportStatus.FINALIZED:
        return report
    document = latest_document(db, report.id, for_update=True)
    if document.version != expected_version:
        raise HTTPException(status_code=409, detail={"error_code": "VERSION_CONFLICT", "current_version": document.version})
    advisory_failures = [
        item for item in release_gate_checks(db, report, document)
        if item.get("severity") == "BLOCKING" and item.get("status") != "PASSED"
    ]
    try:
        assert_page_one_layout_fits(report, document.content)
    except DisclaimerResourceError as error:
        raise HTTPException(status_code=503, detail={
            "error_code": "DISCLAIMER_RESOURCE_INVALID",
            "message": "The approved disclaimer resource is unavailable or invalid.",
            "severity": "BLOCKING",
            "fix_hint": "Restore the approved versioned disclaimer resource before finalizing.",
        }) from error
    except PageOneLayoutOverflowError as error:
        raise HTTPException(status_code=422, detail={
            "error_code": error.error_code,
            "message": str(error),
            "severity": "BLOCKING",
            "fix_hint": error.fix_hint,
            "findings": list(error.findings),
        }) from error

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
