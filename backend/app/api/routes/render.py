"""Generate a finalized report on each download; no artifact bytes are retained (ADR-0029)."""
import json
import logging
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core import download_signing
from app.domain.service.audit import audit
from app.domain.service.exports import export_source
from app.domain.page_one_presentation import PageOneLayoutOverflowError
from app.rendering.artifacts import generate_export, renderer_version_for
from app.rendering.disclaimer import DisclaimerResourceError, disclaimer_audit_fields
from app.rendering.download_response import ExportResponse
from .deps import Db, RequestId

router = APIRouter()
logger = logging.getLogger(__name__)
OutputFormat = Literal["html", "pdf", "docx"]


def _resource(report_id: str, version: int, format_name: str) -> str:
    return json.dumps(["report-export", report_id, version, format_name], separators=(",", ":"))


@router.get("/reports/{report_id}/exports/{format_name}/download")
def download_report(report_id: str, format_name: OutputFormat, request: Request, db: Db):
    _, document = export_source(db, report_id)
    expires = int(time.time()) + settings.download_ttl_seconds
    signature = download_signing.sign(_resource(report_id, document.version, format_name), request.state.principal.subject, expires)
    return JSONResponse({
        "download_url": f"{settings.api_prefix}/reports/{report_id}/exports/{format_name}/content?version={document.version}&expires={expires}&signature={signature}",
        "expires_at": expires,
    }, headers={"Cache-Control": "no-store"})


@router.get("/reports/{report_id}/exports/{format_name}/content", include_in_schema=False)
def export_content(report_id: str, format_name: OutputFormat, version: int, expires: int,
                   signature: str, request: Request, db: Db, x_request_id: RequestId):
    report, document = export_source(db, report_id, version)
    if not download_signing.verify(_resource(report_id, version, format_name), request.state.principal.subject, expires, signature):
        raise HTTPException(403, detail={"error_code": "DOWNLOAD_SIGNATURE_INVALID"})
    details = {"document_version": version, "document_checksum": document.checksum,
               "snapshot_id": document.snapshot_id, "format": format_name,
               "template_version": document.template_version,
               "design_token_version": document.content.get("design_token_version"),
               "renderer_version": renderer_version_for(format_name),
               "lane": document.content.get("lane", report.lane),
               "language_mode": document.content.get("language_mode", report.language_mode),
               **disclaimer_audit_fields()}
    export = None
    try:
        export = generate_export(report, document, format_name)
        details.update(
            size_bytes=export.size_bytes,
            checksum=export.checksum,
            content_manifest=export.content_manifest,
            disclaimer_version=export.disclaimer_version,
            disclaimer_checksum=export.disclaimer_checksum,
        )
        # This proves generation, not that the browser received or saved the file.
        audit(db, "export.generated", "report", report_id, x_request_id, details)
        db.commit()
        return ExportResponse(export)
    except Exception as error:
        if export is not None:
            export.cleanup()
        db.rollback()
        code = (
            "DISCLAIMER_RESOURCE_INVALID"
            if isinstance(error, DisclaimerResourceError)
            else "PAGE_ONE_LAYOUT_OVERFLOW"
            if isinstance(error, PageOneLayoutOverflowError)
            else "PDF_LAYOUT_OVERFLOW"
            if isinstance(error, ValueError) and str(error).startswith("PDF_LAYOUT_OVERFLOW")
            else "EXPORT_FAILED"
        )
        # Renderer exceptions can contain private file paths or URLs; log only safe diagnostics.
        logger.error("Report export failed: %s (%s)", code, type(error).__name__)
        audit(db, "export.failed", "report", report_id, x_request_id, {**details, "error_code": code})
        db.commit()
        raise HTTPException(422 if code in {"PDF_LAYOUT_OVERFLOW", "PAGE_ONE_LAYOUT_OVERFLOW"} else 503, detail={
            "error_code": code,
            "message": (
                "The approved disclaimer resource is unavailable or invalid."
                if code == "DISCLAIMER_RESOURCE_INVALID"
                else str(error)
                if code == "PAGE_ONE_LAYOUT_OVERFLOW"
                else "The report could not be generated."
            ),
            "fix_hint": (
                "Restore the approved versioned disclaimer resource before retrying the download."
                if code == "DISCLAIMER_RESOURCE_INVALID"
                else error.fix_hint
                if isinstance(error, PageOneLayoutOverflowError)
                else "Retry the download. If it fails again, check the API rendering logs and resources."
            ),
            **(
                {"findings": list(error.findings)}
                if isinstance(error, PageOneLayoutOverflowError)
                else {}
            ),
        }) from None
