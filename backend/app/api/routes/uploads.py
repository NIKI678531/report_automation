"""Bounded reading of uploaded files.

Every upload endpoint used to do ``data = await file.read()`` and *then* compare ``len(data)``
against a bare magic number, so the ceiling was announced only after the whole file had been
materialised. These helpers check the declared size first, read in chunks with a running cap, and
report the limit through the standard error envelope so the UI can tell the user what to do.

The limits themselves are settings, not literals, because nginx's ``client_max_body_size`` has to
be configured to match: if the proxy is the stricter of the two it answers with a bare HTML 413
that carries none of this structure.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

_CHUNK_BYTES = 1024 * 1024


def _too_large(limit_bytes: int, error_code: str) -> HTTPException:
    megabytes = limit_bytes / (1024 * 1024)
    return HTTPException(
        status_code=413,
        detail={
            "error_code": error_code,
            "message": f"The upload exceeds the {megabytes:.0f} MB limit for this endpoint.",
            "severity": "BLOCKING",
            "fix_hint": "Split the file, or export only the rows for the reporting period.",
        },
    )


async def read_upload(file: UploadFile, limit_bytes: int, *, error_code: str = "FILE_TOO_LARGE") -> bytes:
    """Read an upload, refusing anything over ``limit_bytes``.

    The declared size is checked first so an oversized file is rejected without being copied at
    all; the chunked loop then re-checks, because a chunked transfer declares no size and would
    otherwise be unbounded.
    """
    declared = getattr(file, "size", None)
    if declared is not None and declared > limit_bytes:
        raise _too_large(limit_bytes, error_code)
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK_BYTES):
        total += len(chunk)
        if total > limit_bytes:
            raise _too_large(limit_bytes, error_code)
        chunks.append(chunk)
    return b"".join(chunks)


def ensure_total_within(total_bytes: int, limit_bytes: int, *, error_code: str = "BATCH_TOO_LARGE") -> None:
    """Guard the aggregate size of a multi-file batch."""
    if total_bytes > limit_bytes:
        raise _too_large(limit_bytes, error_code)
