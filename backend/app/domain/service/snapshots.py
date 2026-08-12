"""Snapshot lifecycle: composition, dataset slots, imports and clears.

A :class:`DataSnapshot` is the immutable input side of the lineage chain
(``ReportConfig -> DataSnapshot -> MetricValue -> ReportDocument -> RenderArtifact``). Every
function here appends a new snapshot rather than editing one, and each snapshot carries the
quality findings that decide whether it is calculable.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from .. import ingestion
from ..calculation import historical_performance, snapshot_checks
from ..document import bind_snapshot, checksum
from ..industry import map_effective_hsics
from ..models import (
    DataImport,
    DataSnapshot,
    Lane,
    ProductCatalog,
    Report,
    ReportDocument,
    ReportStatus,
    SnapshotDataset,
    SnapshotStatus,
)
from ..snapshot_composer import compose_da_report_fragment
from .audit import audit
from .catalog import resolve_product
from .documents import latest_document


_CLEARABLE_DATASETS = frozenset({"constituent_performance", "index_constituents", "constituent_returns"})


def empty_payload(report_date: date) -> dict:
    return {
        "as_of_date": report_date.isoformat(),
        "constituents": [],
        "historical_performance": {"rows": []},
        "company_news": [],
        "analytics": {"top10": [], "sectors": [], "top": [], "bottom": [], "portfolio": []},
        "footnotes": {},
        "datasets": {},
    }


def _snapshot_dataset_specs(payload: dict) -> list[tuple[str, list | dict]]:
    specs: list[tuple[str, list | dict]] = []
    constituents = payload.get("constituents", [])
    if constituents:
        specs.append(("constituent_snapshot", constituents))
        if any(any(row.get(field) is not None or row.get(f"{field}_missing_reason") for field in ("return_1m", "return_3m", "return_6m", "return_ytd")) for row in constituents):
            specs.append(("constituent_period_return", constituents))
    if payload.get("total_return_series"):
        specs.append(("total_return_series", payload["total_return_series"]))
    if payload.get("fund_kpis"):
        specs.append(("fund_kpi_daily", payload["fund_kpis"]))
    if payload.get("trading_calendar"):
        specs.append(("trading_calendar", payload["trading_calendar"]))
    if payload.get("index_events"):
        specs.append(("index_event", payload["index_events"]))
    if payload.get("industry_master"):
        specs.append(("industry_master", payload["industry_master"]))
    return specs


def ensure_snapshot_datasets(db: Session, snapshot: DataSnapshot) -> list[SnapshotDataset]:
    existing = list(db.scalars(select(SnapshotDataset).where(SnapshotDataset.snapshot_id == snapshot.id)))
    by_type = {item.dataset_type: item for item in existing}
    dataset_metadata = (snapshot.payload or {}).get("datasets", {})

    def metadata_for(dataset_type: str) -> dict:
        candidates = {
            "constituent_snapshot": ("constituent_performance", "index_constituents"),
            "constituent_period_return": ("constituent_performance", "constituent_returns"),
            "index_event": ("index_events",),
        }.get(dataset_type, (dataset_type,))
        for key in candidates:
            metadata = dataset_metadata.get(key) if isinstance(dataset_metadata, dict) else None
            if isinstance(metadata, dict):
                return metadata
        return {}

    for dataset_type, rows in _snapshot_dataset_specs(snapshot.payload or {}):
        if dataset_type in by_type:
            continue
        metadata = metadata_for(dataset_type)
        row_count = int(metadata.get("row_count") or len(rows))
        row_checksum = str(metadata.get("checksum") or checksum(rows))
        source_type = str(metadata.get("source_type") or snapshot.source_policy)
        source_object = str(
            metadata.get("source_object")
            or metadata.get("filename")
            or metadata.get("import_id")
            or source_type
        )
        lineage = dict(metadata.get("lineage") or {})
        lineage.update({
            "source_system": lineage.get("source_system") or source_type,
            "dataset_type": dataset_type,
            "snapshot_id": snapshot.id,
            "as_of_date": snapshot.as_of_date.isoformat(),
            "mapping_version": str(metadata.get("mapping_version") or snapshot.mapping_version),
            "checksum": row_checksum,
        })
        item = SnapshotDataset(
            snapshot_id=snapshot.id,
            dataset_type=dataset_type,
            source_type=source_type,
            source_object=source_object,
            row_count=row_count,
            coverage=Decimal("1") if dataset_type == "constituent_snapshot" and snapshot.status == SnapshotStatus.VALID else None,
            checksum=row_checksum,
            parser_version=metadata.get("parser_version"),
            mapping_version=str(metadata.get("mapping_version") or snapshot.mapping_version),
            validation_results=list(snapshot.quality_results or []),
            lineage=lineage,
        )
        db.add(item)
        by_type[dataset_type] = item
    db.flush()
    return list(by_type.values())


def dataset_present(payload: dict, dataset_type: str) -> bool:
    if dataset_type in set(payload.get("datasets", {})):
        return True
    constituents = payload.get("constituents", [])
    if dataset_type == "constituent_performance":
        return bool(constituents) and all(
            all(row.get(field) is not None or row.get(f"{field}_missing_reason") for field in ingestion.RETURN_FIELDS)
            for row in constituents
        )
    if dataset_type == "index_constituents":
        return bool(constituents)
    if dataset_type == "constituent_returns":
        return bool(constituents) and any(
            any(row.get(field) is not None for field in ingestion.RETURN_FIELDS)
            for row in constituents
        )
    if dataset_type == "total_return_series":
        return bool(payload.get("total_return_series"))
    if dataset_type == "fund_kpi_daily":
        return bool(payload.get("fund_kpis"))
    if dataset_type == "trading_calendar":
        return bool(payload.get("trading_calendar"))
    if dataset_type == "index_events":
        return bool(payload.get("index_events"))
    if dataset_type == "industry_master":
        return bool(payload.get("industry_master"))
    return False


def snapshot_dataset_type(dataset_type: str) -> str:
    return {
        "constituent_performance": "constituent_snapshot",
        "index_constituents": "constituent_snapshot",
        "constituent_returns": "constituent_period_return",
        "fund_kpi_daily": "fund_kpi_daily",
        "index_events": "index_event",
    }.get(dataset_type, dataset_type)


def missing_required_slots(payload: dict) -> list[str]:
    """Required slots that have not been applied to this snapshot yet.

    A slot counts as present once ``dataset_present`` can see the data it owns, whatever supplied
    it: the constituent CSV upload, the read-only DA-Report SQLite snapshot, or the industry
    master. The industry master is required but is not an upload slot, so it is appended here.
    """
    missing = [key for key in ingestion.REQUIRED_SLOTS if not dataset_present(payload, key)]
    if not dataset_present(payload, "industry_master"):
        missing.append("industry_master")
    return missing


def overlay_slot(base: dict, spec: "ingestion.DatasetSpec", payload: dict) -> list[dict]:
    """Write only the fields this slot owns onto the base snapshot, keyed by security code.

    Returns findings describing rows the slot could not be joined to, so a mismatched
    constituent set is visible instead of silently dropped.
    """
    findings: list[dict] = []
    direct_slots = {
        "total_return_series": "total_return_series",
        "fund_kpi_daily": "fund_kpis",
        "trading_calendar": "trading_calendar",
        "index_events": "index_events",
    }
    if spec.key in direct_slots:
        target = direct_slots[spec.key]
        base[target] = json.loads(json.dumps(payload.get(target, [])))
        if spec.key == "total_return_series":
            base["historical_performance"] = {"rows": []}
        return findings
    if spec.key == "constituent_performance":
        incoming = json.loads(json.dumps(payload.get("constituents", [])))
        base["constituents"] = incoming
        base["return_periods"] = json.loads(json.dumps(payload.get("return_periods", {})))
        base["as_of_date"] = incoming[0]["as_of_date"] if incoming else base.get("as_of_date")
        return findings
    if spec.key == "index_constituents":
        incoming = payload.get("constituents", [])
        existing = {row["security_code"]: row for row in base.get("constituents", [])}
        merged = []
        for row in incoming:
            carried = existing.get(row["security_code"], {})
            # Preserve fields other slots already contributed for this security.
            item = {key: value for key, value in carried.items() if key not in spec.owns}
            item.update(row)
            merged.append(item)
        dropped = sorted(set(existing) - {row["security_code"] for row in incoming}, key=lambda code: int(code) if code.isdigit() else 0)
        for code in dropped:
            findings.append({
                "error_code": "CONSTITUENT_REMOVED", "severity": "INFO", "entity_id": code,
                "message": f"Security {code} is no longer in the index and was removed from the snapshot.",
                "fix_hint": "This is expected when the index rebalances.",
            })
        base["constituents"] = merged
        base["as_of_date"] = incoming[0]["as_of_date"] if incoming else base.get("as_of_date")
        return findings

    rows = payload.get("constituent_returns") or []
    by_code = {row["security_code"]: row for row in rows}
    constituents = base.get("constituents", [])
    if not constituents:
        findings.append({
            "error_code": "CONSTITUENT_SET_MISSING", "severity": "BLOCKING", "entity_id": None,
            "message": f"{spec.title} was applied before any index constituents exist.",
            "fix_hint": "Upload the index constituents slot first; it defines which securities the report covers.",
        })
        return findings
    for row in constituents:
        source = by_code.get(row["security_code"])
        if not source:
            continue
        for field in spec.owns:
            if field in source:
                row[field] = source[field]
    unmatched = sorted(set(by_code) - {row["security_code"] for row in constituents}, key=lambda code: int(code) if code.isdigit() else 0)
    for code in unmatched:
        findings.append({
            "error_code": "CONSTITUENT_SET_MISMATCH", "severity": "WARNING", "entity_id": code,
            "message": f"{spec.title} carries security {code}, which is not in the index constituent list.",
            "fix_hint": "The file covers a different index date; the extra row was ignored.",
        })
    uncovered = sorted(
        (row["security_code"] for row in constituents if not any(row.get(field) is not None for field in spec.owns)),
        key=lambda code: int(code) if code.isdigit() else 0,
    )
    error_code = "SECTOR_MAPPING_MISSING" if "sector" in spec.owns else "RETURNS_MISSING"
    for code in uncovered:
        name = next((row.get("name_en") for row in constituents if row["security_code"] == code), code)
        findings.append({
            "error_code": error_code, "severity": "WARNING", "entity_id": code,
            "message": f"{name} ({code}) has no value from {spec.title}.",
            "fix_hint": "Cover this security with an approved sector override, or refresh the vendor file." if "sector" in spec.owns else "Refresh the Bloomberg workbook so this security is included.",
        })
    return findings


def require_complete_snapshot(snapshot: DataSnapshot | None) -> None:
    """Reject work that would present an incomplete snapshot as finished output.

    A PENDING snapshot is a legitimate intermediate state while slots are still being uploaded,
    but calculating or finalizing from one would publish blanks as if they were facts.
    """
    if snapshot is None:
        raise HTTPException(status_code=422, detail={"error_code": "SNAPSHOT_REQUIRED", "message": "This report has no active data snapshot."})
    if snapshot.status == SnapshotStatus.VALID:
        return
    missing = missing_required_slots(snapshot.payload or {})
    titles = [ingestion.REGISTRY[key].title for key in missing if key in ingestion.REGISTRY]
    raise HTTPException(status_code=422, detail={
        "error_code": "SNAPSHOT_INCOMPLETE",
        "message": "The active snapshot is not complete enough to calculate from." if missing else "The active snapshot failed its blocking quality checks.",
        "severity": "BLOCKING",
        "fix_hint": f"Upload the remaining dataset(s): {', '.join(titles)}." if titles else "Resolve the reported quality check failures and apply the dataset again.",
        "missing_slots": missing,
        "snapshot_status": snapshot.status.value,
    })


def fixture_payload(product_code: str, report_date) -> dict:
    if product_code != "3033" or report_date.isoformat() != "2026-06-30":
        raise HTTPException(status_code=422, detail={
            "error_code": "FIXTURE_NOT_AVAILABLE",
            "message": f"No approved golden fixture exists for {product_code} on {report_date.isoformat()}.",
            "severity": "BLOCKING",
            "fix_hint": "Use an approved CDB snapshot or upload a complete dataset for this product.",
        })
    path: Path = settings.service_root / "tests" / "fixtures" / "3033_202606" / "snapshot.json"
    if not path.exists():
        raise HTTPException(status_code=503, detail={"error_code": "FIXTURE_MISSING", "message": f"Golden fixture is missing: {path}"})
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Transcribed prose, kept beside the transcribed numbers. Merged only here, on the one code
    # path that binds on the TESTING lane, so no production report can be handed writing it did
    # not do. `bind_snapshot` refuses it on any other lane and labels it where it lands.
    editorial_path = path.with_name("editorial.json")
    if editorial_path.exists():
        payload.update(json.loads(editorial_path.read_text(encoding="utf-8")))
    return payload


def _stage_auto_snapshot(
    db: Session,
    report: Report,
    product: ProductCatalog,
    request_id: str,
    preserve_constituents: bool,
) -> DataSnapshot:
    payload = empty_payload(report.report_date)
    active_snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    if preserve_constituents and active_snapshot and dataset_present(active_snapshot.payload or {}, "constituent_performance"):
        active_payload = active_snapshot.payload or {}
        payload["constituents"] = json.loads(json.dumps(active_payload.get("constituents", [])))
        if active_payload.get("return_periods"):
            payload["return_periods"] = json.loads(json.dumps(active_payload["return_periods"]))
        for key in ("constituent_performance", "index_constituents", "constituent_returns"):
            metadata = (active_payload.get("datasets") or {}).get(key)
            if isinstance(metadata, dict):
                payload["datasets"][key] = json.loads(json.dumps(metadata))

    fragment, provider_findings = compose_da_report_fragment(product, report.report_date)
    for key in ("total_return_series", "fund_kpis", "trading_calendar", "index_events"):
        if key in fragment:
            payload[key] = fragment[key]
    payload["datasets"].update(fragment.get("datasets", {}))
    payload["constituent_index_code"] = report.constituent_index_code
    if payload.get("total_return_series"):
        try:
            payload["historical_performance"] = historical_performance(
                payload["total_return_series"], report.report_date, product.formula_profile,
            )
        except ValueError as error:
            provider_findings.append({
                "check_id": "HISTORICAL_PERIODS_INCOMPLETE",
                "error_code": "HISTORICAL_PERIODS_INCOMPLETE",
                "severity": "BLOCKING",
                "status": "FAILED",
                "message": str(error),
                "actual": None,
                "threshold": "Common FUND and BENCHMARK endpoints for 1M, 3M, 6M and YTD",
                "fix_hint": "Extend the DA-Report Total Return observations to every required common endpoint.",
            })
    mapping_findings = map_effective_hsics(db, payload, report.report_date)
    results = [*snapshot_checks(payload, product.expected_constituent_count), *provider_findings, *mapping_findings]
    missing = missing_required_slots(payload)
    blocked = [
        item for item in results
        if item.get("severity") == "BLOCKING" and item.get("status", "FAILED") != "PASSED"
    ]
    valid = not missing and not blocked
    has_upload = dataset_present(payload, "constituent_performance")
    snapshot = DataSnapshot(
        report_id=report.id,
        as_of_date=report.report_date,
        source_policy="DA_REPORT_PLUS_UPLOAD" if has_upload else "DA_REPORT_AUTO",
        lane=Lane.PRODUCTION.value,
        mapping_version="da-report-monthly-v1",
        status=SnapshotStatus.VALID if valid else SnapshotStatus.PENDING,
        checksum=checksum(payload),
        payload=payload,
        quality_results=results,
    )
    db.add(snapshot)
    db.flush()
    ensure_snapshot_datasets(db, snapshot)
    report.active_snapshot_id = snapshot.id
    report.lane = snapshot.lane
    report.status = ReportStatus.DATA_READY if valid else ReportStatus.DRAFT
    current = latest_document(db, report.id)
    bound = bind_snapshot(current.content, payload, lane=snapshot.lane)
    bound["snapshot_id"] = snapshot.id
    document = ReportDocument(
        report_id=report.id,
        version=current.version + 1,
        snapshot_id=snapshot.id,
        template_version=report.template_version,
        language_mode=report.language_mode,
        content=bound,
        checksum=checksum(bound),
    )
    db.add(document)
    report.version += 1
    audit(db, "snapshot.auto_refreshed", "snapshot", snapshot.id, request_id, {
        "status": snapshot.status.value,
        "missing_slots": missing,
        "provider_findings": [item.get("check_id") for item in provider_findings],
        "preserved_constituents": has_upload,
    })
    return snapshot


def create_snapshot(db: Session, report: Report, source_policy: str, mapping_version: str, request_id: str) -> DataSnapshot:
    # Deferred to break the one cycle in this package: a new valid snapshot triggers a
    # recalculation, while `calculations` reads snapshot helpers from here. The dependency
    # points snapshots -> calculations only at call time, never at import time.
    from .calculations import run_calculation

    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED", "message": "Create a revision before refreshing data."})
    if source_policy == "DA_REPORT_AUTO":
        product = resolve_product(db, report.product_code, report.report_date)
        snapshot = _stage_auto_snapshot(db, report, product, request_id, preserve_constituents=True)
        db.commit()
        db.refresh(snapshot)
        if snapshot.status == SnapshotStatus.VALID:
            run_calculation(db, report, request_id)
            db.refresh(snapshot)
        return snapshot
    if source_policy != "GOLDEN_FIXTURE":
        raise HTTPException(status_code=422, detail={
            "error_code": "CONNECTOR_NOT_CONFIGURED",
            "message": f"{source_policy} is not configured in this environment.",
            "severity": "BLOCKING",
            "fix_hint": "Configure the approved CDB connector or use the golden fixture in local/UAT.",
        })
    # The golden fixture is transcribed from an approved report, not derived from a source system,
    # so it only ever lands on the TESTING lane — and only where that lane is deliberately enabled.
    if not settings.allow_testing_lane:
        raise HTTPException(status_code=422, detail={
            "error_code": "TESTING_LANE_DISABLED",
            "message": "The golden fixture is testing data and the testing lane is disabled in this environment.",
            "severity": "BLOCKING",
            "fix_hint": "Upload the report's datasets, or set ALLOW_TESTING_LANE=true in a local/UAT environment.",
        })
    product = resolve_product(db, report.product_code, report.report_date)
    payload = fixture_payload(report.product_code, report.report_date)
    results = snapshot_checks(payload, product.expected_constituent_count)
    valid = all(item["status"] == "PASSED" for item in results if item["severity"] == "BLOCKING")
    snapshot = DataSnapshot(
        report_id=report.id,
        as_of_date=report.report_date,
        source_policy=source_policy,
        lane=Lane.TESTING.value,
        mapping_version=mapping_version,
        status=SnapshotStatus.VALID if valid else SnapshotStatus.INVALID,
        checksum=checksum(payload),
        payload=payload,
        quality_results=results,
    )
    db.add(snapshot)
    db.flush()
    ensure_snapshot_datasets(db, snapshot)
    if valid:
        report.active_snapshot_id = snapshot.id
        report.lane = snapshot.lane
        report.status = ReportStatus.DATA_READY
        current = latest_document(db, report.id)
        bound = bind_snapshot(current.content, payload, lane=snapshot.lane, include_testing_editorial=True)
        bound["snapshot_id"] = snapshot.id
        next_document = ReportDocument(
            report_id=report.id,
            version=current.version + 1,
            snapshot_id=snapshot.id,
            template_version=report.template_version,
            language_mode=report.language_mode,
            content=bound,
            checksum=checksum(bound),
        )
        db.add(next_document)
        report.version += 1
    audit(db, "snapshot.created", "snapshot", snapshot.id, request_id, {"status": snapshot.status.value})
    db.commit()
    db.refresh(snapshot)
    return snapshot


def apply_import(db: Session, report: Report, data_import: DataImport, reason: str | None, request_id: str) -> DataSnapshot:
    from .calculations import run_calculation  # see the note in `create_snapshot`

    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={"error_code": "REPORT_FINALIZED", "message": "Create a revision before applying an import."})
    if data_import.report_id != report.id:
        raise HTTPException(status_code=404, detail={"error_code": "IMPORT_NOT_FOUND"})
    if data_import.status != "VALIDATED":
        raise HTTPException(status_code=409, detail={"error_code": "IMPORT_NOT_APPLICABLE", "message": "Import is not in VALIDATED state."})
    product = resolve_product(db, report.product_code, report.report_date)
    active_snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    replacing_dataset = dataset_present(active_snapshot.payload or {}, data_import.dataset_type) if active_snapshot else False
    previous_dataset = db.scalar(select(SnapshotDataset).where(
        SnapshotDataset.snapshot_id == active_snapshot.id,
        SnapshotDataset.dataset_type == snapshot_dataset_type(data_import.dataset_type),
    )) if active_snapshot else None
    if replacing_dataset and not reason:
        raise HTTPException(status_code=422, detail={
            "error_code": "IMPORT_REASON_REQUIRED",
            "message": "Replacing the active dataset requires a reason.",
            "severity": "BLOCKING",
            "fix_hint": "Describe why the current dataset is being replaced.",
        })
    if active_snapshot:
        base = json.loads(json.dumps(active_snapshot.payload))
    else:
        base = empty_payload(report.report_date)
    spec = ingestion.get_spec(data_import.dataset_type)
    if spec is None:
        raise HTTPException(status_code=409, detail={
            "error_code": "LEGACY_IMPORT_RETIRED",
            "message": f"The {data_import.dataset_type} import path has been retired.",
            "severity": "BLOCKING",
            "fix_hint": "Upload the corresponding logical dataset slots instead.",
        })
    findings: list[dict] = []
    findings = overlay_slot(base, spec, data_import.payload)
    incoming_index_code = str(data_import.payload.get("constituent_index_code") or "")
    if data_import.dataset_type == "constituent_performance" and incoming_index_code != report.constituent_index_code:
        findings.append({
            "error_code": "CONSTITUENT_INDEX_MISMATCH",
            "severity": "BLOCKING",
            "entity_id": incoming_index_code or None,
            "message": f"The file covers {incoming_index_code or 'an unspecified index'}, not {report.constituent_index_code}.",
            "fix_hint": "Upload the constituent-performance file for the report's configured index.",
        })
    base["constituent_index_code"] = report.constituent_index_code
    findings.extend(map_effective_hsics(db, base, report.report_date))
    metadata_payload_key = spec.payload_key or {
        "constituent_performance": "constituents",
        "index_constituents": "constituents",
        "constituent_returns": "constituent_returns",
        "total_return_series": "total_return_series",
        "fund_kpi_daily": "fund_kpis",
        "trading_calendar": "trading_calendar",
        "index_events": "index_events",
    }.get(spec.key, spec.key)
    base.setdefault("datasets", {})[data_import.dataset_type] = {
        "import_id": data_import.id,
        "filename": data_import.original_filename,
        "checksum": data_import.checksum,
        "source_type": "UPLOAD",
        "source_object": data_import.original_filename,
        "row_count": len(data_import.payload.get(metadata_payload_key, [])),
        "parser_version": data_import.parser_version,
        "mapping_version": str(data_import.mapping_version or data_import.parser_version),
        "lineage": {
            "source_system": "UPLOAD",
            "import_id": data_import.id,
            "original_filename": data_import.original_filename,
            "file_checksum": data_import.checksum,
        },
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    results = snapshot_checks(base, product.expected_constituent_count)
    missing = missing_required_slots(base)
    blocked = [item for item in results if item["severity"] == "BLOCKING" and item["status"] != "PASSED"]
    blocked.extend(item for item in findings if item.get("severity") == "BLOCKING" and item.get("status", "FAILED") != "PASSED")
    # A slot upload is incomplete by design until every required slot has landed, so an incomplete
    # snapshot is recorded as PENDING rather than rejected. Only a snapshot that is complete *and*
    # passes every blocking check becomes VALID and therefore calculable.
    complete = not missing
    if complete and blocked and data_import.dataset_type in {"constituent_performance", "constituents", "historical_performance", "final_analytics"}:
        raise HTTPException(status_code=422, detail={"error_code": "IMPORT_QUALITY_BLOCKED", "checks": blocked})
    status = SnapshotStatus.VALID if complete and not blocked else SnapshotStatus.PENDING
    contains_da_report = any(
        isinstance(metadata, dict) and metadata.get("source_type") == "DA_REPORT_SQLITE"
        for metadata in (base.get("datasets") or {}).values()
    )
    snapshot = DataSnapshot(
        report_id=report.id,
        as_of_date=report.report_date,
        source_policy="DA_REPORT_PLUS_UPLOAD" if contains_da_report else "UPLOAD_OVERRIDE",
        # An upload layered onto testing data does not launder it back to PRODUCTION: the fixture
        # rows it did not overwrite are still in the payload.
        lane=active_snapshot.lane if active_snapshot else Lane.PRODUCTION.value,
        mapping_version=data_import.parser_version,
        status=status,
        checksum=checksum(base),
        payload=base,
        quality_results=[*results, *findings],
    )
    db.add(snapshot); db.flush()
    ensure_snapshot_datasets(db, snapshot)
    report.active_snapshot_id = snapshot.id
    report.lane = snapshot.lane
    report.status = (
        ReportStatus.DATA_READY if status == SnapshotStatus.VALID
        else ReportStatus.QA_BLOCKED if complete and blocked
        else ReportStatus.DRAFT
    )
    current = latest_document(db, report.id)
    bound = bind_snapshot(current.content, base, lane=snapshot.lane)
    bound["snapshot_id"] = snapshot.id
    next_document = ReportDocument(
        report_id=report.id, version=current.version + 1, snapshot_id=snapshot.id,
        template_version=report.template_version, language_mode=report.language_mode,
        content=bound, checksum=checksum(bound),
    )
    db.add(next_document)
    report.version += 1
    data_import.status = "APPLIED"
    data_import.reason = reason
    data_import.applied_snapshot_id = snapshot.id
    audit(db, "import.applied", "import", data_import.id, request_id, {
        "apply_mode": "OVERWRITE" if replacing_dataset else "FIRST_APPLY",
        "reason": reason, "snapshot_id": snapshot.id, "dataset_type": data_import.dataset_type,
        "previous_snapshot_id": active_snapshot.id if active_snapshot else None,
        "replaced_snapshot_dataset_id": previous_dataset.id if previous_dataset else None,
        "replaced_checksum": previous_dataset.checksum if previous_dataset else None,
        "diff": data_import.diff,
        "snapshot_status": status.value, "missing_slots": missing, "findings": len(findings),
    })
    if status == SnapshotStatus.VALID:
        try:
            run_calculation(db, report, request_id)
        except Exception:
            db.rollback()
            raise
    else:
        db.commit()
    db.refresh(snapshot)
    return snapshot


def discard_import(db: Session, report: Report, import_id: str, request_id: str) -> DataImport:
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={
            "error_code": "REPORT_FINALIZED",
            "message": "Create a revision before discarding report imports.",
        })
    data_import = db.get(DataImport, import_id)
    if not data_import or data_import.report_id != report.id:
        raise HTTPException(status_code=404, detail={"error_code": "IMPORT_NOT_FOUND"})
    if data_import.status == "APPLIED":
        raise HTTPException(status_code=409, detail={
            "error_code": "IMPORT_ALREADY_APPLIED",
            "message": "Applied data must be cleared from its dataset slot instead.",
            "fix_hint": "Use Delete data on the applied dataset card.",
        })
    if data_import.status == "DISCARDED":
        return data_import
    previous_status = data_import.status
    data_import.status = "DISCARDED"
    audit(db, "import.discarded", "import", data_import.id, request_id, {
        "dataset_type": data_import.dataset_type,
        "filename": data_import.original_filename,
        "previous_status": previous_status,
    })
    db.commit()
    db.refresh(data_import)
    return data_import


def clear_dataset(
    db: Session,
    report: Report,
    dataset_type: str,
    expected_version: int,
    request_id: str,
) -> DataSnapshot:
    if dataset_type not in _CLEARABLE_DATASETS:
        raise HTTPException(status_code=422, detail={
            "error_code": "DATASET_CLEAR_UNSUPPORTED",
            "message": f"The {dataset_type} dataset cannot be cleared from this workspace.",
            "fix_hint": f"Clearable datasets: {', '.join(sorted(_CLEARABLE_DATASETS))}.",
        })
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(status_code=409, detail={
            "error_code": "REPORT_FINALIZED",
            "message": "Create a revision before clearing applied data.",
        })
    if report.version != expected_version:
        raise HTTPException(status_code=409, detail={
            "error_code": "VERSION_CONFLICT",
            "message": "The report changed before the dataset could be cleared.",
            "current_version": report.version,
        })
    active_snapshot = db.get(DataSnapshot, report.active_snapshot_id) if report.active_snapshot_id else None
    if not active_snapshot or not dataset_present(active_snapshot.payload or {}, dataset_type):
        raise HTTPException(status_code=409, detail={
            "error_code": "DATASET_NOT_APPLIED",
            "message": f"The {dataset_type} dataset is not applied to the active snapshot.",
        })
    if dataset_type == "index_constituents" and dataset_present(active_snapshot.payload or {}, "constituent_returns"):
        raise HTTPException(status_code=409, detail={
            "error_code": "DATASET_DEPENDENCY_BLOCKED",
            "message": "Constituent returns must be cleared before index constituents.",
            "dependencies": ["constituent_returns"],
            "fix_hint": "Delete the Constituent returns data first, then retry.",
        })

    base = json.loads(json.dumps(active_snapshot.payload or {}))
    datasets = base.setdefault("datasets", {})
    removed_metadata = dict(datasets.pop(dataset_type, {}) or {})
    if dataset_type == "constituent_returns":
        for row in base.get("constituents", []):
            for field in ingestion.RETURN_FIELDS:
                row.pop(field, None)
                row.pop(f"{field}_missing_reason", None)
        base.pop("return_periods", None)
    elif dataset_type == "constituent_performance":
        base["constituents"] = []
        base.pop("return_periods", None)
    else:
        base["constituents"] = []

    base["analytics"] = {"top10": [], "sectors": [], "top": [], "bottom": [], "portfolio": []}
    base.pop("metrics", None)
    base.pop("formula_version", None)
    footnotes = dict(base.get("footnotes") or {})
    footnotes.pop("constituents", None)
    footnotes.pop("analytics", None)
    base["footnotes"] = footnotes

    product = resolve_product(db, report.product_code, report.report_date)
    results = snapshot_checks(base, product.expected_constituent_count)
    missing = missing_required_slots(base)
    snapshot = DataSnapshot(
        report_id=report.id,
        as_of_date=report.report_date,
        source_policy=active_snapshot.source_policy,
        lane=active_snapshot.lane,
        mapping_version=active_snapshot.mapping_version,
        status=SnapshotStatus.PENDING,
        checksum=checksum(base),
        payload=base,
        quality_results=results,
    )
    db.add(snapshot)
    db.flush()
    ensure_snapshot_datasets(db, snapshot)

    current = latest_document(db, report.id)
    content = bind_snapshot(current.content, base, lane=snapshot.lane)
    content["snapshot_id"] = snapshot.id
    content.pop("formula_version", None)
    content.pop("module_bindings", None)
    document = ReportDocument(
        report_id=report.id,
        version=current.version + 1,
        snapshot_id=snapshot.id,
        template_version=report.template_version,
        language_mode=report.language_mode,
        content=content,
        checksum=checksum(content),
    )
    db.add(document)
    report.active_snapshot_id = snapshot.id
    report.lane = snapshot.lane
    report.status = ReportStatus.DRAFT
    report.version += 1
    audit(db, "dataset.cleared", "snapshot", snapshot.id, request_id, {
        "dataset_type": dataset_type,
        "previous_snapshot_id": active_snapshot.id,
        "cleared_snapshot_id": snapshot.id,
        "removed_import_id": removed_metadata.get("import_id"),
        "removed_filename": removed_metadata.get("filename"),
        "removed_checksum": removed_metadata.get("checksum"),
        "missing_slots": missing,
    })
    db.commit()
    db.refresh(snapshot)
    return snapshot
