"""Shared report lifecycle guards for every state-changing service."""

from fastapi import HTTPException

from ..models import Report, ReportStatus


def ensure_report_not_archived(report: Report) -> None:
    if report.status == ReportStatus.ARCHIVED:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "REPORT_ARCHIVED",
                "message": "Archived reports are read-only.",
            },
        )


def ensure_report_editable(report: Report) -> None:
    ensure_report_not_archived(report)
    if report.status == ReportStatus.FINALIZED:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "REPORT_FINALIZED",
                "message": "Finalized reports are immutable.",
            },
        )
