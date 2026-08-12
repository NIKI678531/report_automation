"""Company-news candidates and the report's news selection.

News is editorial input, never a source of report numbers, so this module touches no snapshot
arithmetic. It records which candidates a report has seen, how confidently each was matched to a
constituent, and which ones the editor placed in the document.

Provider failures are surfaced verbatim (code, message, retryable) and never swallowed: a fetch
that half-succeeded would look like "no news this month", which is a different fact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.da_report import DaReportProviderError, get_company_news_catalog_item
from app.integrations.news import NewsProviderError, fetch_news, get_spec
from ..models import (
    DataSnapshot,
    NewsFetchRun,
    NewsItem,
    Report,
    ReportNewsCandidate,
    ReportNewsSelection,
    ReportStatus,
    SnapshotStatus,
    utcnow,
)
from ..schemas import NewsCandidateFetch, NewsCreate, NewsRead, NewsSelectionUpdate
from .audit import audit
from .documents import latest_document, update_document


def upsert_news_candidates(db: Session, report: Report, candidates: list[dict], request_id: str, provider: str = "DA_REPORT") -> tuple[list[NewsItem], int]:
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
                match_status="CONFIRMED" if security_code or metadata.get("matched_security_code") or metadata.get("catalog_verified") else "NEEDS_REVIEW",
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


def list_news_candidates_for_report_context(db: Session, report: Report) -> list[NewsItem]:
    context_report_ids = set(db.scalars(
        select(Report.id).where(
            Report.product_code == report.product_code,
            Report.report_date == report.report_date,
        )
    ))
    rows = db.execute(
        select(NewsItem, ReportNewsCandidate.report_id, ReportNewsCandidate.provider)
        .join(ReportNewsCandidate, ReportNewsCandidate.news_item_id == NewsItem.id)
        .where(ReportNewsCandidate.report_id.in_(context_report_ids))
        .order_by(NewsItem.published_at.desc())
    )
    items: dict[str, NewsItem] = {}
    for item, candidate_report_id, provider in rows:
        if candidate_report_id == report.id or provider != "MANUAL":
            items[item.id] = item
    for item in db.scalars(select(NewsItem).order_by(NewsItem.published_at.desc())):
        metadata = item.metadata_json or {}
        linked_report_ids = set(metadata.get("report_ids", []))
        if item.id not in items and linked_report_ids.intersection(context_report_ids):
            if linked_report_ids == {report.id} or metadata.get("provider") != "MANUAL":
                items[item.id] = item
    month_start = report.report_date.replace(day=1)
    hkt = ZoneInfo("Asia/Hong_Kong")

    def in_report_month(item: NewsItem) -> bool:
        published_at = item.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        published_date = published_at.astimezone(hkt).date()
        return month_start <= published_date <= report.report_date

    return sorted((item for item in items.values() if in_report_month(item)), key=lambda item: item.published_at, reverse=True)


def resolve_news_constituent_snapshot(db: Session, report: Report) -> DataSnapshot | None:
    if report.active_snapshot_id:
        return db.get(DataSnapshot, report.active_snapshot_id)
    return db.scalar(
        select(DataSnapshot)
        .join(Report, Report.id == DataSnapshot.report_id)
        .where(
            Report.product_code == report.product_code,
            Report.report_date == report.report_date,
            DataSnapshot.status == SnapshotStatus.VALID,
        )
        .order_by(DataSnapshot.created_at.desc())
    )


async def fetch_report_news(db: Session, report: Report, command: NewsCandidateFetch, request_id: str) -> dict:
    """Pull candidates from one provider for this report's month and record them.

    ``command.ensure`` makes the call idempotent for the UI's automatic first load: a window that
    already succeeded is reported back as skipped rather than re-fetched, and a missing or
    not-yet-valid snapshot is a skip reason instead of an error, because the caller is a page load
    rather than a deliberate user action.
    """
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    month_start = report.report_date.replace(day=1)
    from_date = command.from_date or month_start
    to_date = command.to_date or report.report_date
    if from_date > to_date or to_date > report.report_date:
        raise HTTPException(status_code=422, detail={"error_code": "NEWS_DATE_RANGE_INVALID", "message": "News dates must be ordered and cannot exceed the report date."})
    symbols: list[str] = []
    constituents: list[dict] = []
    try:
        provider_key = get_spec(command.provider).key
    except NewsProviderError as error:
        raise HTTPException(status_code=error.http_status, detail={"error_code": error.code, "message": error.message, "retryable": error.retryable}) from error
    context_snapshot = resolve_news_constituent_snapshot(db, report)
    if not context_snapshot and command.ensure:
        return {
            "provider": provider_key,
            "fetched": 0,
            "created": 0,
            "ensured": False,
            "skip_reason": "CONSTITUENT_SNAPSHOT_UNAVAILABLE" if command.scope == "CONSTITUENTS" else "SNAPSHOT_UNAVAILABLE",
            "items": [],
        }
    if command.scope == "CONSTITUENTS":
        if not context_snapshot:
            raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED", "message": "Constituent news requires an active snapshot."})
        if context_snapshot.status.value != "VALID":
            if command.ensure:
                return {
                    "provider": provider_key,
                    "fetched": 0,
                    "created": 0,
                    "ensured": False,
                    "skip_reason": "SNAPSHOT_NOT_VALID",
                    "items": [],
                }
            raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_NOT_VALID", "message": "Constituent news requires a valid active snapshot."})
        constituents = list(context_snapshot.payload.get("constituents", []))
        symbols = sorted({str(row.get("ticker", "")).upper() for row in constituents if row.get("ticker")})
        if not symbols:
            raise HTTPException(status_code=422, detail={"error_code": "CONSTITUENT_TICKERS_REQUIRED"})
    fetch_run = None
    try:
        if command.ensure:
            existing_items = list_news_candidates_for_report_context(db, report)
            successful_run = db.scalar(select(NewsFetchRun).where(
                NewsFetchRun.snapshot_id == context_snapshot.id,
                NewsFetchRun.provider == provider_key,
                NewsFetchRun.scope == command.scope,
                NewsFetchRun.from_date == from_date,
                NewsFetchRun.to_date == to_date,
                NewsFetchRun.status == "SUCCEEDED",
            ).order_by(NewsFetchRun.completed_at.desc()))
            if successful_run:
                return {
                    "provider": provider_key,
                    "fetched": 0,
                    "created": 0,
                    "ensured": False,
                    "skip_reason": "CANDIDATES_ALREADY_EXIST" if existing_items else "WINDOW_ALREADY_ENSURED",
                    "items": [NewsRead.model_validate(item).model_dump() for item in existing_items],
                }
            fetch_run = db.scalar(select(NewsFetchRun).where(
                NewsFetchRun.report_id == report.id,
                NewsFetchRun.snapshot_id == context_snapshot.id,
                NewsFetchRun.provider == provider_key,
                NewsFetchRun.scope == command.scope,
                NewsFetchRun.from_date == from_date,
                NewsFetchRun.to_date == to_date,
            ))
            if fetch_run is None:
                fetch_run = NewsFetchRun(
                    report_id=report.id,
                    snapshot_id=context_snapshot.id,
                    provider=provider_key,
                    scope=command.scope,
                    from_date=from_date,
                    to_date=to_date,
                    status="RUNNING",
                )
                db.add(fetch_run)
            else:
                fetch_run.status = "RUNNING"
                fetch_run.error_code = None
            db.commit()
        provider, candidates = await fetch_news(
            command.provider,
            command.scope,
            symbols,
            from_date,
            to_date,
            command.page,
            command.limit,
            constituents=constituents,
        )
    except NewsProviderError as error:
        if fetch_run:
            fetch_run.status = "FAILED"
            fetch_run.error_code = error.code
            fetch_run.completed_at = utcnow()
            db.commit()
        raise HTTPException(status_code=error.http_status, detail={"error_code": error.code, "message": error.message, "retryable": error.retryable}) from error
    items, created = upsert_news_candidates(db, report, candidates, request_id, provider=provider)
    if fetch_run:
        fetch_run.status = "SUCCEEDED"
        fetch_run.fetched_count = len(candidates)
        fetch_run.matched_count = len(items)
        fetch_run.completed_at = utcnow()
        db.commit()
    return {"provider": provider, "fetched": len(candidates), "created": created, "ensured": bool(command.ensure), "items": [NewsRead.model_validate(item).model_dump() for item in items]}


def add_manual_news_candidate(db: Session, report: Report, command: NewsCreate, request_id: str) -> NewsItem:
    """Manually add a candidate the provider missed, scoped to this report like a fetched one."""
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    published_at = command.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    candidate = {
        "source_name": command.source_name, "source_url": command.source_url, "published_at": published_at,
        "title": command.title, "summary": command.summary, "ticker": command.ticker,
        "metadata_json": {"provider": "MANUAL", "scope": "MANUAL", "site": urlparse(command.source_url).hostname},
    }
    items, _ = upsert_news_candidates(db, report, [candidate], request_id, provider="MANUAL")
    return items[0]


async def select_report_news(db: Session, report: Report, command: NewsSelectionUpdate, request_id: str) -> dict:
    """Replace the document's company-news block with the editor's ordered selection.

    Catalog entries picked straight from DA-Report are materialized into local ``NewsItem`` rows
    first, so a finalized document never references a row that only exists in the vendor.
    """
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    current = latest_document(db, report.id)
    if current.version != command.version:
        raise HTTPException(status_code=409, detail={"error_code": "VERSION_CONFLICT", "current_version": current.version})
    ordered = sorted(command.items, key=lambda value: value.position)
    references = [
        f"LOCAL:{item.news_item_id}" if item.news_item_id else f"DA_REPORT:{item.external_id}"
        for item in ordered
    ]
    if len(references) != len(set(references)):
        raise HTTPException(status_code=422, detail={"error_code": "NEWS_SELECTION_DUPLICATE"})
    resolved: list[tuple[object, NewsItem]] = []
    external: list[tuple[object, dict]] = []
    for item in ordered:
        if item.news_item_id:
            news = db.get(NewsItem, item.news_item_id)
            if not news:
                raise HTTPException(status_code=422, detail={"error_code": "NEWS_NOT_FOUND", "news_item_id": item.news_item_id})
            resolved.append((item, news))
            continue
        try:
            catalog_item = await get_company_news_catalog_item(str(item.external_id))
        except DaReportProviderError as error:
            raise HTTPException(
                status_code=error.http_status,
                detail={"error_code": error.code, "message": error.message, "retryable": error.retryable},
            ) from error
        external.append((item, catalog_item))
    if external:
        candidates = []
        for _, catalog_item in external:
            published_at = datetime.fromisoformat(str(catalog_item["published_at"]).replace("Z", "+00:00"))
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            candidates.append({
                "source_name": catalog_item["source_name"],
                "source_url": catalog_item["source_url"],
                "published_at": published_at,
                "title": catalog_item["title"],
                "summary": catalog_item["summary"],
                "ticker": None,
                "metadata_json": {
                    "provider": "DA_REPORT",
                    "scope": "CATALOG",
                    "site": urlparse(catalog_item["source_url"]).hostname,
                    "external_id": catalog_item["external_id"],
                    "source_code": catalog_item["source_code"],
                    "category": catalog_item["category"],
                    "region": catalog_item["region"],
                    "sentiment": catalog_item["sentiment"],
                    "importance_score": catalog_item["importance_score"],
                    "model": catalog_item["model"],
                    "fetched_at": catalog_item["fetched_at"],
                    "published_at_source": catalog_item["published_at_source"],
                    "match_method": "DA_REPORT_CORPORATE_ENRICHMENT",
                    "catalog_verified": True,
                },
            })
        materialized, _ = upsert_news_candidates(db, report, candidates, request_id, provider="DA_REPORT")
        resolved.extend((item, news) for (item, _), news in zip(external, materialized, strict=True))
    resolved.sort(key=lambda value: value[0].position)
    resolved_ids = [news.id for _, news in resolved]
    if len(resolved_ids) != len(set(resolved_ids)):
        raise HTTPException(status_code=422, detail={"error_code": "NEWS_SELECTION_DUPLICATE"})
    db.query(ReportNewsSelection).filter(ReportNewsSelection.report_id == report.id).delete()
    selected = []
    for item, news in resolved:
        news_published_at = news.published_at
        if news_published_at.tzinfo is None:
            news_published_at = news_published_at.replace(tzinfo=timezone.utc)
        published_hkt = news_published_at.astimezone(ZoneInfo("Asia/Hong_Kong"))
        db.add(ReportNewsSelection(report_id=report.id, news_item_id=news.id, position=item.position, title_override=item.title_override, summary_override=item.summary_override))
        metadata = news.metadata_json or {}
        selected.append({
            "news_item_id": news.id,
            "provider": metadata.get("provider"),
            "external_id": metadata.get("external_id"),
            "title": item.title_override or news.title,
            "summary": item.summary_override or news.summary,
            "source_name": news.source_name,
            "source_url": news.source_url,
            "published_at": news.published_at.isoformat(),
            "published_at_hkt": published_hkt.strftime("%Y-%m-%d %H:%M HKT"),
            "published_at_source": metadata.get("published_at_source"),
            "fetched_at": metadata.get("fetched_at"),
            "ticker": news.ticker,
            "region": metadata.get("region"),
            "sentiment": metadata.get("sentiment"),
            "importance_score": metadata.get("importance_score"),
            "model": metadata.get("model"),
        })
    content = dict(current.content); content["sections"] = dict(content["sections"]); content["sections"]["company_news"] = selected
    document = update_document(db, report, current.version, content, request_id)
    return {"version": document.version, "items": selected}
