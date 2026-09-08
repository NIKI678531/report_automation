"""Delete export scratch files after success, disconnect or a failed response send."""
import anyio
from starlette.responses import FileResponse

from .artifacts import GeneratedExport


class ExportResponse(FileResponse):
    def __init__(self, export: GeneratedExport):
        self.export = export
        super().__init__(export.path, media_type=export.mime_type, filename=export.filename,
                         headers={"Cache-Control": "no-store", "Accept-Ranges": "none"})

    async def __call__(self, scope, receive, send):
        # Each request regenerates the bytes; resuming ranges from an earlier export is invalid.
        scope = {**scope, "headers": [(key, value) for key, value in scope.get("headers", [])
                                     if key.lower() not in {b"range", b"if-range"}]}
        scope["extensions"] = {key: value for key, value in scope.get("extensions", {}).items()
                               if key != "http.response.pathsend"}
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(self.export.cleanup)
