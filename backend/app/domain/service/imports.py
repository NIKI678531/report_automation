"""Upload staging and the dataset-slot view.

Staging turns a file into an inspectable :class:`DataImport` row: it parses, quality-checks and
diffs the upload against the active snapshot, then records every finding on the row. It
deliberately does not touch a snapshot — a rejected file has to stay queryable in the report's
history, and applying an import is a separate, explicit act that appends a new snapshot. That
half of the lifecycle lives in :mod:`.snapshots`, next to the other snapshot-appending operations.

``..imports`` in this module is ``app.domain.imports`` (the diff engine); ``.`` is this package.
"""

from __future__ import annotations

import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ingestion
from ..imports import diff_dataset
from ..industry import effective_hsics_records
from ..metrics.quality_checks import import_checks
from ..models import DataImport, DataSnapshot, MappingProfile, Report, ReportStatus
from ..validation import blocking_findings
from .audit import audit
from .snapshots import dataset_present


def stage_import(
    db: Session,
    report: Report,
    dataset_type: str,
    filename: str,
    content_type: str,
    data: bytes,
    request_id: str,
    batch_id: str | None = None,
) -> tuple[DataImport, bool]:
    """Record one upload as a ``DataImport``.

    Returns the row plus whether applying it would overwrite data already in the active snapshot,
    which the caller turns into the apply mode the reviewer is asked to confirm.
    """
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED"})
    spec = ingestion.get_spec(dataset_type)
    if spec is None:
        raise HTTPException(status_code=422, detail={
            "error_code": "UNSUPPORTED_DATASET",
            "message": f"Unknown dataset type '{dataset_type}'.",
            "fix_hint": f"Supported datasets: {', '.join(sorted(ingestion.REGISTRY))}.",
        })
    profile = None
    profile_matches: list[tuple[MappingProfile, object]] = []
    if spec.requires_profile:
        approved_profiles = list(db.scalars(select(MappingProfile).where(MappingProfile.status == "APPROVED")))
        profile_matches = ingestion.matching_profiles(approved_profiles, filename, data)
        matching_dataset = [item for item in profile_matches if item[0].dataset_type == dataset_type]
        if len(matching_dataset) == 1:
            profile = matching_dataset[0][0]
    try:
        payload, collector = ingestion.parse(dataset_type, filename, data, report.report_date, profile)
    except UnicodeError as error:
        raise HTTPException(status_code=422, detail={
            "error_code": "IMPORT_DECODE_FAILED", "message": "The file could not be decoded as UTF-8.",
            "severity": "BLOCKING", "fix_hint": "Re-export the file as UTF-8 (or UTF-8 with BOM) and upload again.",
        }) from error
    # A file with bad rows is a first-class, inspectable resource rather than a 4xx: the user needs
    # to see every finding at once, and REJECTED imports stay queryable in the report's history.
    if spec.requires_profile and profile is None and profile_matches:
        candidate_types = sorted({item[0].dataset_type for item in profile_matches})
        collector = ingestion.FindingCollector()
        collector.add(
            "MAP-001",
            f"'{filename}' does not uniquely match the requested {dataset_type} profile.",
            fix_hint=f"This file matches: {', '.join(candidate_types)}. Select the corresponding dataset or approve a new profile.",
            entity_id=candidate_types[0],
        )
        payload = {}
    # Import-stage quality gate. It previously keyed off {"constituents", "final_analytics"},
    # neither of which is an `ingestion.REGISTRY` slot, so the branch was unreachable and no
    # upload was ever quality-checked before it reached a snapshot. A blocking failure now
    # rejects the import instead of being recorded on a VALIDATED row nobody reads.
    quality = [] if collector.has_blocking() or not payload else import_checks(payload, dataset_type)
    rejected = collector.has_blocking() or not payload or bool(blocking_findings(quality))
    validations = [*quality, *collector.as_dicts()]
    active_payload: dict = {}
    if report.active_snapshot_id:
        active_snapshot = db.get(DataSnapshot, report.active_snapshot_id)
        active_payload = active_snapshot.payload if active_snapshot else {}
    replacing_dataset = dataset_present(active_payload, dataset_type)
    if rejected:
        diff = {"summary": {"added": 0, "removed": 0, "changed": 0}}
    elif dataset_type in {"constituent_performance", "index_constituents"}:
        diff = diff_dataset("constituents", payload, active_payload)
    else:
        row_keys = ("constituent_returns", "total_return_series", "fund_kpis", "trading_calendar", "index_events")
        rows = next((payload[key] for key in row_keys if payload.get(key)), [])
        diff = {"summary": {"added": 0, "removed": 0, "changed": len(rows)}, "rows": len(rows)}
        if dataset_type == "constituent_returns":
            active_codes = {row["security_code"] for row in active_payload.get("constituents", [])}
            covered = len([row for row in rows if row["security_code"] in active_codes]) if active_codes else 0
            diff.update({"covered": covered, "uncovered": max(len(active_codes) - covered, 0)})
    item = DataImport(
        report_id=report.id, batch_id=batch_id, dataset_type=dataset_type, original_filename=filename,
        mime_type=content_type or "application/octet-stream", size_bytes=len(data), checksum=hashlib.sha256(data).hexdigest(),
        parser_version=f"{dataset_type}-mapping-v2", mapping_profile_id=profile.id if profile else None,
        mapping_version=profile.version if profile else None, payload=payload, validation_results=validations,
        status=("NEEDS_MAPPING" if rejected and any(str(finding.get("check_id") or finding.get("error_code") or "").startswith("MAP-") for finding in validations) else "REJECTED") if rejected else "VALIDATED",
        diff=diff,
    )
    db.add(item); db.flush()
    audit(db, "import.rejected" if rejected else "import.validated", "import", item.id, request_id, {
        "filename": item.original_filename, "dataset_type": dataset_type, **collector.summary(),
    })
    db.commit(); db.refresh(item)
    return item, replacing_dataset


def _row_count(payload: dict | None) -> int:
    if not payload:
        return 0
    for key in ("constituents", "constituent_returns", "total_return_series", "fund_kpis", "trading_calendar", "index_events"):
        if key in payload:
            return len(payload[key])
    return 0


def _snapshot_row_count(payload: dict, dataset_type: str) -> int:
    if dataset_type == "constituent_performance":
        return len(payload.get("constituents", [])) if dataset_present(payload, dataset_type) else 0
    if dataset_type == "index_constituents":
        return len(payload.get("constituents", []))
    if dataset_type == "constituent_returns":
        return len([
            row for row in payload.get("constituents", [])
            if any(row.get(field) is not None for field in ingestion.RETURN_FIELDS)
        ])
    payload_keys = {
        "total_return_series": "total_return_series",
        "fund_kpi_daily": "fund_kpis",
        "trading_calendar": "trading_calendar",
        "index_events": "index_events",
    }
    if dataset_type == "total_return_series" and not payload.get("total_return_series"):
        return len((payload.get("historical_performance") or {}).get("rows", []))
    return len(payload.get(payload_keys.get(dataset_type, dataset_type), []))


def dataset_slots(db: Session, report: Report) -> list[dict]:
    """Per-slot ingestion state, so the UI can show what is loaded and what is still missing.

    The industry master is appended last: it is required for every industry aggregation but is
    centrally managed rather than uploaded per report, so it has no ``ingestion.REGISTRY`` slot.
    """
    latest_imports: dict[str, DataImport] = {}
    for item in db.scalars(select(DataImport).where(DataImport.report_id == report.id).order_by(DataImport.created_at.asc())):
        latest_imports[item.dataset_type] = item
    snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    applied_metadata = (snapshot.payload or {}).get("datasets", {}) if snapshot else {}
    slots = []
    for key, spec in ingestion.REGISTRY.items():
        is_applied = bool(snapshot and dataset_present(snapshot.payload or {}, key))
        metadata = applied_metadata.get(key, {}) if isinstance(applied_metadata, dict) else {}
        applied_import_id = metadata.get("import_id") if isinstance(metadata, dict) else None
        applied_import = db.get(DataImport, applied_import_id) if applied_import_id else None
        latest_import = latest_imports.get(key)
        candidate = latest_import if latest_import and latest_import.status not in {"APPLIED", "DISCARDED"} else None
        item = applied_import if is_applied else candidate
        findings = list(item.validation_results or []) if item else []
        slots.append({
            "key": key,
            "title": spec.title,
            "description": spec.description,
            "required": spec.required,
            "accepts": list(spec.accepts),
            "state": "APPLIED" if is_applied else item.status if item else "MISSING",
            "latest_import_id": item.id if item else None,
            "filename": item.original_filename if item else None,
            "rows": _snapshot_row_count(snapshot.payload or {}, key) if is_applied and snapshot else _row_count(item.payload) if item else 0,
            "source_type": metadata.get("source_type") if isinstance(metadata, dict) else None,
            "source_name": metadata.get("source_name") if isinstance(metadata, dict) else None,
            "uploaded_at": item.created_at.isoformat() if item else None,
            "blocking": len([finding for finding in findings if finding.get("severity") == "BLOCKING" and finding.get("status") != "PASSED"]),
            "warnings": len([finding for finding in findings if finding.get("severity") == "WARNING" and finding.get("status") != "PASSED"]),
            "applied_snapshot_id": snapshot.id if is_applied and snapshot else None,
        })
    industry_rows = effective_hsics_records(db, report.report_date)
    industry_versions = {row.version for row in industry_rows}
    industry_applied = bool(snapshot and dataset_present(snapshot.payload or {}, "industry_master"))
    slots.append({
        "key": "industry_master",
        "title": "HSICS industry master",
        "description": "Centrally managed report-date-effective HSICS taxonomy used for every industry aggregation.",
        "required": True,
        "accepts": [".csv"],
        "state": "APPLIED" if industry_applied else "AVAILABLE" if len(industry_versions) == 1 else "MISSING",
        "latest_import_id": None,
        "filename": None,
        "rows": len(industry_rows),
        "source_type": "INDUSTRY_MASTER" if industry_applied else None,
        "source_name": "HSICS industry master" if industry_applied else None,
        "uploaded_at": None,
        "blocking": 0 if len(industry_versions) == 1 else 1,
        "warnings": 0,
        "applied_snapshot_id": snapshot.id if industry_applied else None,
    })
    return slots
