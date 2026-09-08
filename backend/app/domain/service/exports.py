"""Resolve an authorized, finalized version without refreshing any external data."""
from copy import deepcopy
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..document import checksum
from ..models import ReportDocument, ReportStatus
from .reports import get_report


def export_source(db: Session, report_id: str, version: int | None = None):
    report = get_report(db, report_id)
    if report.status not in {ReportStatus.FINALIZED, ReportStatus.ARCHIVED} or not report.finalized_document_version:
        raise HTTPException(422, detail={"error_code": "FINALIZATION_REQUIRED", "message": "Finalize the report before downloading."})
    fixed_version = report.finalized_document_version
    if version is not None and version != fixed_version:
        raise HTTPException(409, detail={"error_code": "EXPORT_VERSION_MISMATCH", "message": "This download does not match the finalized version."})
    document = db.scalar(select(ReportDocument).where(ReportDocument.report_id == report.id, ReportDocument.version == fixed_version))
    if document is None:
        raise HTTPException(404, detail={"error_code": "DOCUMENT_NOT_FOUND", "message": "Finalized document not found."})
    if checksum(document.content) != document.checksum:
        raise HTTPException(409, detail={"error_code": "DOCUMENT_CHECKSUM_MISMATCH", "message": "The finalized document failed its integrity check."})
    # Materialize before releasing the transaction: rendering must not lazy-load a newer row.
    report_copy = SimpleNamespace(**{column.key: getattr(report, column.key) for column in report.__table__.columns})
    document_copy = SimpleNamespace(**{column.key: deepcopy(getattr(document, column.key)) for column in document.__table__.columns})
    db.rollback()
    return report_copy, document_copy
