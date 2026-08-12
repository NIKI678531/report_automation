"""Classification, preview and one-shot application of constituent import batches."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ingestion
from ..calculation import snapshot_checks
from ..document import bind_snapshot, checksum
from ..industry import map_effective_hsics
from ..models import (
    DataImport,
    DataSnapshot,
    ImportBatch,
    Lane,
    MappingProfile,
    Report,
    ReportDocument,
    ReportStatus,
    SnapshotStatus,
)
from .audit import audit
from .catalog import resolve_product
from .documents import latest_document
from .imports import stage_import
from .snapshots import (
    dataset_present,
    empty_payload,
    ensure_snapshot_datasets,
    missing_required_slots,
    overlay_slot,
)

MAX_FILES = 20
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_BATCH_BYTES = 100 * 1024 * 1024
_SPLIT_TYPES = ("index_constituents", "constituent_returns")


def _csv_headers(data: bytes) -> set[str]:
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig")))
        return {ingestion._normalize_header(value) for value in next(reader, [])}
    except (UnicodeError, csv.Error):
        return set()


def _unsupported_import(
    db: Session,
    report: Report,
    batch: ImportBatch,
    filename: str,
    content_type: str,
    data: bytes,
    status: str,
    finding: dict[str, Any],
    dataset_type: str = "unclassified",
) -> DataImport:
    item = DataImport(
        report_id=report.id,
        batch_id=batch.id,
        dataset_type=dataset_type,
        original_filename=filename,
        mime_type=content_type or "application/octet-stream",
        size_bytes=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
        parser_version="batch-classifier-v1",
        status=status,
        payload={},
        validation_results=[finding],
        diff={"summary": {"added": 0, "removed": 0, "changed": 0}},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _detect_dataset(db: Session, filename: str, data: bytes) -> tuple[str | None, bool]:
    """Return detected type and whether failure should block rather than be skipped."""
    suffix = Path(filename).suffix.lower()
    headers = _csv_headers(data) if suffix == ".csv" else set()
    canonical = {ingestion._normalize_header(value) for value in ingestion.CONSTITUENT_PERFORMANCE_COLUMNS}
    if canonical and canonical.issubset(headers):
        return "constituent_performance", True
    profiles = list(db.scalars(select(MappingProfile).where(MappingProfile.status == "APPROVED")))
    try:
        matches = ingestion.matching_profiles(profiles, filename, data)
    except Exception:
        return ("constituent_returns", True) if suffix in {".xlsx", ".xlsm"} else (None, False)
    types = sorted({profile.dataset_type for profile, _candidate in matches if profile.dataset_type in _SPLIT_TYPES})
    if len(types) == 1:
        return types[0], True
    if len(types) > 1:
        return "ambiguous", True
    hsi_markers = {ingestion._normalize_header(value) for value in ("Idx Cde", "Lcal Cde", "Pct Idx Wgt")}
    if hsi_markers & headers:
        return "index_constituents", True
    return None, False


def _file_view(item: DataImport) -> dict[str, Any]:
    payload = item.payload or {}
    rows = next((payload[key] for key in ("constituents", "constituent_returns") if key in payload), [])
    findings = [finding for finding in (item.validation_results or []) if finding.get("status", "FAILED") != "PASSED"]
    sample = rows[:10]
    columns = [key for key in (sample[0].keys() if sample else ()) if not key.startswith("_")]
    return {
        "id": item.id,
        "filename": item.original_filename,
        "detected_type": item.dataset_type,
        "mapping_version": item.mapping_version,
        "status": item.status,
        "row_count": len(rows),
        "errors": findings,
        "preview": {"columns": columns, "rows": [{key: row.get(key) for key in columns} for row in sample]},
    }


def _recompute_batch(db: Session, batch: ImportBatch) -> ImportBatch:
    items = list(db.scalars(select(DataImport).where(DataImport.batch_id == batch.id).order_by(DataImport.created_at)))
    included = [item for item in items if item.status not in {"EXCLUDED", "UNSUPPORTED", "DISCARDED"}]
    by_type = {
        key: [item for item in included if item.dataset_type == key]
        for key in ("constituent_performance", *_SPLIT_TYPES)
    }
    findings: list[dict[str, Any]] = []
    invalid = [item for item in included if item.status != "VALIDATED"]
    if invalid:
        findings.append({
            "error_code": "BATCH_RECOGNIZED_FILE_INVALID",
            "severity": "BLOCKING",
            "message": "One or more recognized files could not be validated.",
            "files": [item.original_filename for item in invalid],
            "fix_hint": "Correct or exclude each rejected recognized file before applying the batch.",
        })
    if by_type["constituent_performance"] and (by_type["index_constituents"] or by_type["constituent_returns"]):
        findings.append({
            "error_code": "BATCH_SOURCE_MODE_CONFLICT",
            "severity": "BLOCKING",
            "message": "A canonical constituent-performance file cannot be mixed with split identity/return files.",
            "fix_hint": "Exclude either the canonical file or every split-source file.",
        })
    for dataset_type, matches in by_type.items():
        if len(matches) > 1:
            findings.append({
                "error_code": "BATCH_DUPLICATE_SOURCE",
                "severity": "BLOCKING",
                "message": f"Multiple sources were supplied for {dataset_type}.",
                "files": [item.original_filename for item in matches],
                "fix_hint": "Exclude all but one source; the system does not choose precedence automatically.",
            })
    canonical_ready = len(by_type["constituent_performance"]) == 1
    identity_ready = canonical_ready or len(by_type["index_constituents"]) == 1
    returns_ready = canonical_ready or len(by_type["constituent_returns"]) == 1
    if findings:
        status = "BLOCKED"
    elif identity_ready and returns_ready:
        status = "READY"
    else:
        status = "INCOMPLETE"
    batch.status = status
    batch.validation_results = findings
    batch.composition = {
        "mode": "CANONICAL" if canonical_ready else "SPLIT",
        "identity": {"state": "READY" if identity_ready else "MISSING", "import_ids": [item.id for item in by_type["constituent_performance"] or by_type["index_constituents"]]},
        "returns": {"state": "READY" if returns_ready else "MISSING", "import_ids": [item.id for item in by_type["constituent_performance"] or by_type["constituent_returns"]]},
        "unsupported_count": len([item for item in items if item.status == "UNSUPPORTED"]),
    }
    db.commit()
    db.refresh(batch)
    return batch


def batch_view(db: Session, batch: ImportBatch) -> dict[str, Any]:
    items = list(db.scalars(select(DataImport).where(DataImport.batch_id == batch.id).order_by(DataImport.created_at)))
    return {
        "id": batch.id,
        "report_id": batch.report_id,
        "status": batch.status,
        "coverage": batch.composition or {},
        "errors": batch.validation_results or [],
        "reason": batch.reason,
        "applied_snapshot_id": batch.applied_snapshot_id,
        "files": [_file_view(item) for item in items],
    }


def create_import_batch(
    db: Session,
    report: Report,
    files: list[tuple[str, str, bytes]],
    request_id: str,
) -> ImportBatch:
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED", "message": "Create a revision before importing data."})
    if not files or len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail={"error_code": "BATCH_FILE_LIMIT", "message": f"Select between 1 and {MAX_FILES} files."})
    if any(len(data) > MAX_FILE_BYTES for _name, _mime, data in files):
        raise HTTPException(status_code=413, detail={"error_code": "FILE_TOO_LARGE", "message": "Each file is limited to 20 MB."})
    if sum(len(data) for _name, _mime, data in files) > MAX_BATCH_BYTES:
        raise HTTPException(status_code=413, detail={"error_code": "BATCH_TOO_LARGE", "message": "One batch is limited to 100 MB."})
    batch = ImportBatch(report_id=report.id, status="STAGING", validation_results=[], composition={})
    db.add(batch)
    db.commit()
    db.refresh(batch)
    for filename, content_type, data in files:
        dataset_type, recognized = _detect_dataset(db, filename, data)
        if dataset_type == "ambiguous":
            _unsupported_import(db, report, batch, filename, content_type, data, "REJECTED", {
                "error_code": "BATCH_FILE_AMBIGUOUS", "severity": "BLOCKING",
                "message": "The file matches more than one approved layout.",
                "fix_hint": "Remove conflicting columns or use an approved canonical template.",
            }, "ambiguous")
            continue
        if not dataset_type:
            _unsupported_import(db, report, batch, filename, content_type, data, "UNSUPPORTED", {
                "error_code": "UNSUPPORTED_FILE", "severity": "INFO",
                "message": "No approved tabular layout was detected; this file will be skipped.",
                "fix_hint": "No action is needed unless this file was intended to provide constituents or returns.",
            })
            continue
        try:
            stage_import(db, report, dataset_type, filename, content_type, data, request_id, batch.id)
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
            _unsupported_import(db, report, batch, filename, content_type, data, "REJECTED" if recognized else "UNSUPPORTED", {
                "error_code": detail.get("error_code", "IMPORT_PARSE_FAILED"),
                "severity": "BLOCKING" if recognized else "INFO",
                "message": detail.get("message", "The recognized file could not be parsed."),
                "fix_hint": detail.get("fix_hint", "Correct the file and upload it again."),
            }, dataset_type)
    _recompute_batch(db, batch)
    audit(db, "import_batch.staged", "import_batch", batch.id, request_id, {"status": batch.status, "file_count": len(files)})
    db.commit()
    return batch


def get_import_batch(db: Session, report: Report, batch_id: str) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.report_id != report.id:
        raise HTTPException(status_code=404, detail={"error_code": "IMPORT_BATCH_NOT_FOUND"})
    return batch


def exclude_batch_file(db: Session, report: Report, batch_id: str, import_id: str, request_id: str) -> ImportBatch:
    batch = get_import_batch(db, report, batch_id)
    item = db.get(DataImport, import_id)
    if not item or item.batch_id != batch.id:
        raise HTTPException(status_code=404, detail={"error_code": "IMPORT_NOT_FOUND"})
    if batch.status == "APPLIED":
        raise HTTPException(status_code=409, detail={"error_code": "IMPORT_BATCH_APPLIED"})
    item.status = "EXCLUDED"
    audit(db, "import_batch.file_excluded", "import", item.id, request_id, {"batch_id": batch.id})
    db.commit()
    return _recompute_batch(db, batch)


def discard_import_batch(db: Session, report: Report, batch_id: str, request_id: str) -> ImportBatch:
    batch = get_import_batch(db, report, batch_id)
    if batch.status == "APPLIED":
        raise HTTPException(status_code=409, detail={"error_code": "IMPORT_BATCH_APPLIED"})
    batch.status = "DISCARDED"
    audit(db, "import_batch.discarded", "import_batch", batch.id, request_id, {})
    db.commit()
    db.refresh(batch)
    return batch


def apply_import_batch(
    db: Session,
    report: Report,
    batch_id: str,
    expected_version: int,
    reason: str | None,
    request_id: str,
) -> DataSnapshot:
    from .calculations import run_calculation

    batch = get_import_batch(db, report, batch_id)
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED", "message": "Create a revision before applying data."})
    if report.version != expected_version:
        raise HTTPException(status_code=409, detail={"error_code": "VERSION_CONFLICT", "current_version": report.version})
    if batch.status != "READY":
        raise HTTPException(status_code=409, detail={"error_code": "IMPORT_BATCH_NOT_READY", "status": batch.status, "coverage": batch.composition})
    active = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    replacing = bool(active and (dataset_present(active.payload or {}, "index_constituents") or dataset_present(active.payload or {}, "constituent_performance")))
    if replacing and not reason:
        raise HTTPException(status_code=422, detail={
            "error_code": "IMPORT_REASON_REQUIRED", "message": "Replacing the active constituent data requires a reason.",
            "fix_hint": "Describe why the current constituent snapshot is being replaced.",
        })
    base = json.loads(json.dumps(active.payload or {})) if active and active.lane == Lane.PRODUCTION.value else empty_payload(report.report_date)
    base["constituents"] = []
    base.pop("return_periods", None)
    datasets = base.setdefault("datasets", {})
    for key in ("constituent_performance", *_SPLIT_TYPES):
        datasets.pop(key, None)
    items = list(db.scalars(select(DataImport).where(
        DataImport.batch_id == batch.id,
        DataImport.status == "VALIDATED",
    )))
    ordered = sorted(items, key=lambda item: {"index_constituents": 0, "constituent_performance": 0, "constituent_returns": 1}.get(item.dataset_type, 9))
    findings: list[dict[str, Any]] = []
    for item in ordered:
        spec = ingestion.get_spec(item.dataset_type)
        if spec is None:
            continue
        findings.extend(overlay_slot(base, spec, item.payload or {}))
        incoming_index = str((item.payload or {}).get("constituent_index_code") or "").upper()
        if item.dataset_type in {"index_constituents", "constituent_performance"} and incoming_index != report.constituent_index_code.upper():
            findings.append({
                "error_code": "CONSTITUENT_INDEX_MISMATCH", "severity": "BLOCKING", "entity_id": incoming_index or None,
                "message": f"{item.original_filename} covers {incoming_index or 'an unspecified index'}, not {report.constituent_index_code}.",
                "fix_hint": "Upload the constituent file for the report's configured index.",
            })
        payload_key = spec.payload_key or ("constituents" if item.dataset_type == "index_constituents" else item.dataset_type)
        rows = (item.payload or {}).get(payload_key, [])
        datasets[item.dataset_type] = {
            "import_id": item.id, "filename": item.original_filename, "checksum": item.checksum,
            "source_type": "UPLOAD", "source_object": item.original_filename, "row_count": len(rows),
            "parser_version": item.parser_version, "mapping_version": str(item.mapping_version or item.parser_version),
            "lineage": {"source_system": "UPLOAD", "batch_id": batch.id, "import_id": item.id, "file_checksum": item.checksum},
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
    constituent_dates = {str(row.get("as_of_date")) for row in base.get("constituents", []) if row.get("as_of_date")}
    return_end = str((base.get("return_periods") or {}).get("end") or "")
    if return_end and constituent_dates and constituent_dates != {return_end}:
        findings.append({
            "error_code": "BATCH_DATE_MISMATCH", "severity": "BLOCKING",
            "message": f"Constituent as-of {', '.join(sorted(constituent_dates))} differs from return period end {return_end}.",
            "fix_hint": "Use identity and return files from the same month-end.",
        })
    base["constituent_index_code"] = report.constituent_index_code
    findings.extend(map_effective_hsics(db, base, report.report_date))
    product = resolve_product(db, report.product_code, report.report_date)
    results = snapshot_checks(base, product.expected_constituent_count)
    blocked = [item for item in [*results, *findings] if item.get("severity") == "BLOCKING" and item.get("status", "FAILED") != "PASSED"]
    if blocked:
        raise HTTPException(status_code=422, detail={"error_code": "IMPORT_BATCH_QUALITY_BLOCKED", "checks": blocked})
    missing = missing_required_slots(base)
    status = SnapshotStatus.VALID if not missing else SnapshotStatus.PENDING
    contains_da = any(isinstance(value, dict) and value.get("source_type") == "DA_REPORT_SQLITE" for value in datasets.values())
    snapshot = DataSnapshot(
        report_id=report.id,
        as_of_date=report.report_date,
        source_policy="DA_REPORT_PLUS_UPLOAD" if contains_da else "UPLOAD_OVERRIDE",
        lane=Lane.PRODUCTION.value,
        mapping_version="multi-file-batch-v1",
        status=status,
        checksum=checksum(base),
        payload=base,
        quality_results=[*results, *findings],
    )
    db.add(snapshot)
    db.flush()
    ensure_snapshot_datasets(db, snapshot)
    report.active_snapshot_id = snapshot.id
    report.lane = snapshot.lane
    report.status = ReportStatus.DATA_READY if status == SnapshotStatus.VALID else ReportStatus.DRAFT
    for item in ordered:
        item.status = "APPLIED"
        item.reason = reason
        item.applied_snapshot_id = snapshot.id
    batch.status = "APPLIED"
    batch.reason = reason
    batch.applied_snapshot_id = snapshot.id
    audit(db, "import_batch.applied", "import_batch", batch.id, request_id, {
        "snapshot_id": snapshot.id, "file_count": len(ordered), "missing_slots": missing, "reason": reason,
    })
    if status == SnapshotStatus.VALID:
        # The calculator binds the derived payload and appends the single document version for a
        # complete batch. Creating an intermediate document here would make one Apply click look
        # like two reviewer versions.
        run_calculation(db, report, request_id)
    else:
        current = latest_document(db, report.id)
        content = bind_snapshot(current.content, base, lane=snapshot.lane)
        content["snapshot_id"] = snapshot.id
        db.add(ReportDocument(
            report_id=report.id, version=current.version + 1, snapshot_id=snapshot.id,
            template_version=report.template_version, language_mode=report.language_mode,
            content=content, checksum=checksum(content),
        ))
        report.version += 1
        db.commit()
    db.refresh(snapshot)
    return snapshot
