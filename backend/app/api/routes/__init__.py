"""The HTTP surface, assembled as one router and mounted at ``settings.api_prefix``.

This was a single 980-line module. It is now split by resource, with the sub-routers included
here in the order the paths were originally registered so the OpenAPI document keeps its shape.
No two routes overlap, so the order is documentation rather than dispatch logic.

Handlers bind parameters, enforce authorization and shape responses. Anything that decides a fact
about a report — parsing, quality checks, snapshot transitions, document versions — belongs in
``app.domain.service`` instead, so the rule holds whichever caller triggers it.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import admin, catalog, datasets, news, render, reports

router = APIRouter()
router.include_router(admin.router)
router.include_router(catalog.router)
router.include_router(reports.router)
router.include_router(datasets.router)
router.include_router(news.router)
router.include_router(render.router)

__all__ = ["router"]
