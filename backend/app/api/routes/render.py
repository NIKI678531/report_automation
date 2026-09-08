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
from app.rendering.artifacts import generate_export, renderer_version_for
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
               "language_mode": document.content.get("language_mode", report.language_mode)}
    export = None
    try:
        export = generate_export(report, document, format_name)
        details.update(size_bytes=export.size_bytes, checksum=export.checksum, content_manifest=export.content_manifest)
        # This proves generation, not that the browser received or saved the file.
        audit(db, "export.generated", "report", report_id, x_request_id, details)
        db.commit()
        return ExportResponse(export)
    except Exception as error:
        if export is not None:
            export.cleanup()
        db.rollback()
        code = "PDF_LAYOUT_OVERFLOW" if isinstance(error, ValueError) and str(error).startswith("PDF_LAYOUT_OVERFLOW") else "EXPORT_FAILED"
        # Renderer exceptions can contain private file paths or URLs; log only safe diagnostics.
        logger.error("Report export failed: %s (%s)", code, type(error).__name__)
        audit(db, "export.failed", "report", report_id, x_request_id, {**details, "error_code": code})
        db.commit()
        raise HTTPException(422 if code == "PDF_LAYOUT_OVERFLOW" else 503, detail={
            "error_code": code, "message": "The report could not be generated.",
            "fix_hint": "Retry the download. If it fails again, check the API rendering logs and resources.",
        }) from None
