"""Company news: the provider catalog, this report's candidates and the editor's selection.

News is the one part of the report that is editorial rather than derived, so these endpoints
never write a number — the selection lands in the document as cited text.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.domain import service
from app.domain.models import NewsItem
from app.domain.schemas import (
    DaReportNewsCatalogPage,
    NewsCandidateFetch,
    NewsCreate,
    NewsRead,
    NewsSelectionUpdate,
)
from app.integrations import news as news_providers
from app.integrations.da_report import DaReportProviderError, list_company_news_catalog
from .deps import Db, RequestId

router = APIRouter()


@router.get("/news", response_model=list[NewsRead])
def list_news(db: Db, security_code: str | None = None, importance: str | None = None) -> list[NewsItem]:
    query = select(NewsItem).order_by(NewsItem.published_at.desc())
    if security_code:
        query = query.where(NewsItem.security_code == security_code)
    if importance:
        query = query.where(NewsItem.importance == importance.upper())
    return list(db.scalars(query))


@router.get("/news/providers")
def list_news_providers() -> list[dict]:
    """Which news providers this environment can actually reach, so the UI can disable the rest."""
    return news_providers.list_providers()


@router.get("/reports/{report_id}/news/catalog", response_model=DaReportNewsCatalogPage)
async def report_company_news_catalog(
    report_id: str,
    db: Db,
    query: str | None = None,
    source: str | None = None,
    sentiment: str | None = None,
    importance: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    sort: Literal["newest", "oldest"] = "newest",
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    service.get_report(db, report_id)
    try:
        return await list_company_news_catalog(
            query=query,
            source=source,
            sentiment=sentiment,
            importance=importance,
            from_date=from_date,
            to_date=to_date,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )
    except DaReportProviderError as error:
        raise HTTPException(
            status_code=error.http_status,
            detail={"error_code": error.code, "message": error.message, "retryable": error.retryable},
        ) from error


@router.post("/reports/{report_id}/news/candidates/fetch")
async def fetch_news_candidates(report_id: str, command: NewsCandidateFetch, db: Db, x_request_id: RequestId) -> dict:
    report = service.get_report(db, report_id)
    return await service.fetch_report_news(db, report, command, x_request_id)


@router.get("/reports/{report_id}/news/candidates", response_model=list[NewsRead])
def report_news_candidates(
    report_id: str,
    db: Db,
    query: str | None = None,
    source: str | None = None,
    symbol: str | None = None,
    importance: str | None = None,
) -> list[NewsItem]:
    report = service.get_report(db, report_id)
    items = service.list_news_candidates_for_report_context(db, report)
    if query:
        needle = query.casefold()
        items = [item for item in items if needle in f"{item.title} {item.summary} {item.ticker or ''}".casefold()]
    if source:
        items = [item for item in items if item.source_name.casefold() == source.casefold()]
    if symbol:
        items = [item for item in items if (item.ticker or "").casefold() == symbol.casefold()]
    if importance:
        items = [item for item in items if item.importance == importance.upper()]
    return items


@router.post("/reports/{report_id}/news/candidates", response_model=NewsRead, status_code=status.HTTP_201_CREATED)
def add_report_news_candidate(report_id: str, command: NewsCreate, db: Db, x_request_id: RequestId) -> NewsItem:
    report = service.get_report(db, report_id)
    return service.add_manual_news_candidate(db, report, command, x_request_id)


@router.put("/reports/{report_id}/news")
async def select_news(report_id: str, command: NewsSelectionUpdate, db: Db, x_request_id: RequestId) -> dict:
    report = service.get_report(db, report_id)
    return await service.select_report_news(db, report, command, x_request_id)
