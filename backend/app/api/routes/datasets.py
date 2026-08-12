"""The data side of the lineage chain: snapshots, dataset slots, imports and calculation output.

These handlers bind parameters and shape responses only. Parsing, quality checks, diffs and every
snapshot transition live in ``app.domain.service`` so that the same rules apply whichever caller
triggers them.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.domain import service
from app.domain.models import (
    DataImport,
    DataSnapshot,
    MetricValue,
    ModuleSnapshot,
    QualityCheckResult,
    SnapshotDataset,
)
from app.domain.schemas import (
    CalculationRead,
    DatasetClear,
    ImportApply,
    ImportCreateRead,
    ImportRead,
    SnapshotCreate,
    SnapshotRead,
)
from .deps import Db, RequestId

router = APIRouter()


@router.post("/reports/{report_id}/snapshots", response_model=SnapshotRead, status_code=status.HTTP_201_CREATED)
def create_snapshot(report_id: str, command: SnapshotCreate, db: Db, x_request_id: RequestId) -> DataSnapshot:
    report = service.get_report(db, report_id)
    return service.create_snapshot(db, report, command.source_policy, command.mapping_version, x_request_id)


@router.get("/reports/{report_id}/snapshots", response_model=list[SnapshotRead])
def list_snapshots(report_id: str, db: Db) -> list[DataSnapshot]:
    service.get_report(db, report_id)
    return list(db.scalars(select(DataSnapshot).where(DataSnapshot.report_id == report_id).order_by(DataSnapshot.created_at.desc())))


@router.get("/reports/{report_id}/snapshots/{snapshot_id}", response_model=SnapshotRead)
def get_snapshot(report_id: str, snapshot_id: str, db: Db) -> DataSnapshot:
    snapshot = db.get(DataSnapshot, snapshot_id)
    if not snapshot or snapshot.report_id != report_id:
        raise HTTPException(status_code=404, detail={"error_code": "SNAPSHOT_NOT_FOUND"})
    return snapshot


@router.get("/reports/{report_id}/datasets")
def list_datasets(report_id: str, db: Db) -> list[dict]:
    return service.dataset_slots(db, service.get_report(db, report_id))


@router.post("/reports/{report_id}/datasets/{dataset_type}/clear", response_model=SnapshotRead)
def clear_dataset(
    report_id: str,
    dataset_type: str,
    command: DatasetClear,
    db: Db,
    x_request_id: RequestId,
) -> DataSnapshot:
    report = service.get_report(db, report_id)
    return service.clear_dataset(db, report, dataset_type, command.version, x_request_id)


@router.post("/reports/{report_id}/imports", response_model=ImportCreateRead, status_code=status.HTTP_201_CREATED)
async def create_import(
    report_id: str,
    db: Db,
    x_request_id: RequestId,
    file: UploadFile = File(...),
    dataset_type: str = Form(...),
) -> ImportCreateRead:
    report = service.get_report(db, report_id)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"error_code": "FILE_TOO_LARGE", "message": "Uploads are limited to 20 MB."})
    item, replacing_dataset = service.stage_import(
        db, report, dataset_type, file.filename or "upload", file.content_type or "", data, x_request_id,
    )
    return ImportCreateRead(
        **ImportRead.model_validate(item).model_dump(),
        apply_mode="OVERWRITE" if replacing_dataset else "FIRST_APPLY",
        requires_reason=replacing_dataset,
    )


@router.get("/reports/{report_id}/imports", response_model=list[ImportRead])
def list_imports(report_id: str, db: Db) -> list[DataImport]:
    service.get_report(db, report_id)
    return list(db.scalars(select(DataImport).where(DataImport.report_id == report_id).order_by(DataImport.created_at.desc())))


@router.post("/reports/{report_id}/imports/{import_id}/discard", response_model=ImportRead)
def discard_import(report_id: str, import_id: str, db: Db, x_request_id: RequestId) -> DataImport:
    report = service.get_report(db, report_id)
    return service.discard_import(db, report, import_id, x_request_id)


@router.get("/reports/{report_id}/data-diff")
def data_diff(report_id: str, db: Db) -> dict:
    service.get_report(db, report_id)
    item = db.scalar(select(DataImport).where(DataImport.report_id == report_id).order_by(DataImport.created_at.desc()))
    return item.diff if item else {"added": [], "removed": [], "changed": [], "summary": {"added": 0, "removed": 0, "changed": 0}}


@router.post("/reports/{report_id}/imports/{import_id}/apply", response_model=SnapshotRead)
def apply_import(report_id: str, import_id: str, command: ImportApply, db: Db, x_request_id: RequestId) -> DataSnapshot:
    report = service.get_report(db, report_id)
    item = db.get(DataImport, import_id)
    if not item:
        raise HTTPException(status_code=404, detail={"error_code": "IMPORT_NOT_FOUND"})
    return service.apply_import(db, report, item, command.reason, x_request_id)


@router.post("/reports/{report_id}/calculations", response_model=CalculationRead)
def calculations(report_id: str, db: Db, x_request_id: RequestId) -> CalculationRead:
    report = service.get_report(db, report_id)
    metrics, document, results = service.run_calculation(db, report, x_request_id)
    return CalculationRead(snapshot_id=report.active_snapshot_id or "", formula_version=str(document.content["formula_version"]), metrics=metrics, quality_results=results, document_version=document.version)


@router.get("/reports/{report_id}/metrics")
def report_metrics(report_id: str, db: Db) -> list[dict]:
    report = service.get_report(db, report_id)
    if not report.active_snapshot_id:
        return []
    rows = db.scalars(select(MetricValue).where(MetricValue.snapshot_id == report.active_snapshot_id).order_by(MetricValue.metric_code))
    return [{
        "id": item.id,
        "metric_code": item.metric_code,
        "dimension_key": item.dimension_key,
        "value": str(item.value) if item.value is not None else None,
        "raw_value": item.raw_value,
        "unit": item.unit,
        "period_start": item.period_start,
        "period_end": item.period_end,
        "formula_version": item.formula_version,
        "lineage": item.lineage,
    } for item in rows]


@router.get("/reports/{report_id}/modules")
def report_modules(report_id: str, db: Db) -> list[dict]:
    report = service.get_report(db, report_id)
    if not report.active_snapshot_id:
        return []
    rows = db.scalars(select(ModuleSnapshot).where(ModuleSnapshot.snapshot_id == report.active_snapshot_id).order_by(ModuleSnapshot.module_code))
    datasets = {
        item.id: item.dataset_type
        for item in db.scalars(select(SnapshotDataset).where(SnapshotDataset.snapshot_id == report.active_snapshot_id))
    }
    return [{
        "id": item.id,
        "module_code": item.module_code,
        "formula_version": item.formula_version,
        "template_version": item.template_version,
        "source_dataset_ids": item.source_dataset_ids,
        "source_dataset_types": [datasets[dataset_id] for dataset_id in item.source_dataset_ids],
        "metric_value_ids": item.metric_value_ids,
        "checksum": item.checksum,
        "input_checksum": item.input_checksum,
    } for item in rows]


@router.get("/reports/{report_id}/quality-results")
def report_quality_results(report_id: str, db: Db) -> list[dict]:
    report = service.get_report(db, report_id)
    if not report.active_snapshot_id:
        return []
    rows = db.scalars(select(QualityCheckResult).where(QualityCheckResult.snapshot_id == report.active_snapshot_id).order_by(QualityCheckResult.check_id, QualityCheckResult.result_key))
    return [{
        "id": item.id,
        "check_id": item.check_id,
        "severity": item.severity,
        "status": item.status,
        "entity_id": item.entity_id,
        "actual": item.actual,
        "threshold": item.threshold,
        "fix_hint": item.fix_hint,
    } for item in rows]
