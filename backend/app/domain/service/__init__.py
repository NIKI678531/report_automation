"""Session-bound orchestration for the report pipeline.

This was one 1600-line module holding eight unrelated concerns. It is now a package split along
those concerns, with the whole public surface re-exported here so ``from app.domain import
service`` and ``service.<name>`` keep working unchanged.

Modules are layered; each imports only from the ones above it:

``audit`` -> ``catalog`` -> ``documents`` -> ``snapshots`` -> ``imports`` -> ``calculations``
-> ``reports``

``news`` sits beside them and reaches only as far up as ``documents``, because selecting news
writes a new document version. The single exception to the layering is
``snapshots.create_snapshot`` / ``snapshots.apply_import``, which call ``run_calculation`` through
a function-local import: a new valid snapshot triggers a recalculation, so that one edge points
back up the stack at call time only.
"""

from __future__ import annotations

from .audit import audit
from .calculations import persist_calculation_records, run_calculation
from .catalog import import_industry_master, import_products, list_products, resolve_product
from .documents import ai_assisted_draft, latest_document, update_document
from .imports import dataset_slots, stage_import
from .news import (
    add_manual_news_candidate,
    fetch_report_news,
    list_news_candidates_for_report_context,
    list_report_news_candidates,
    resolve_news_constituent_snapshot,
    select_report_news,
    upsert_news_candidates,
)
from .reports import (
    ai_number_check,
    create_report,
    create_revision,
    finalize,
    get_report,
    release_gate_checks,
)
from .snapshots import (
    apply_import,
    clear_dataset,
    create_snapshot,
    dataset_present,
    discard_import,
    empty_payload,
    ensure_snapshot_datasets,
    fixture_payload,
    missing_required_slots,
    overlay_slot,
    require_complete_snapshot,
    snapshot_dataset_type,
)

__all__ = [
    "add_manual_news_candidate",
    "ai_assisted_draft",
    "ai_number_check",
    "apply_import",
    "audit",
    "clear_dataset",
    "create_report",
    "create_revision",
    "create_snapshot",
    "dataset_present",
    "dataset_slots",
    "discard_import",
    "empty_payload",
    "ensure_snapshot_datasets",
    "fetch_report_news",
    "finalize",
    "fixture_payload",
    "get_report",
    "import_industry_master",
    "import_products",
    "latest_document",
    "list_news_candidates_for_report_context",
    "list_products",
    "list_report_news_candidates",
    "missing_required_slots",
    "overlay_slot",
    "persist_calculation_records",
    "release_gate_checks",
    "require_complete_snapshot",
    "resolve_news_constituent_snapshot",
    "resolve_product",
    "run_calculation",
    "select_report_news",
    "snapshot_dataset_type",
    "stage_import",
    "update_document",
    "upsert_news_candidates",
]
