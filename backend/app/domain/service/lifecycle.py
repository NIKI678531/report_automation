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
    """Reject only archived reports.

    A report with a finalized document may start a new in-place working version.  The prior
    ``finalized_document_version`` remains the downloadable publication until a reviewer
    finalizes the newer document.
    """

    ensure_report_not_archived(report)
