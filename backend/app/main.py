from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import settings
from app.core.security import AuthorizationMiddleware


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url="/docs",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(AuthorizationMiddleware)
    application.include_router(router, prefix=settings.api_prefix)

    @application.exception_handler(HTTPException)
    async def structured_http_error(request: Request, error: HTTPException):
        # FastAPI wraps `detail` in {"detail": ...}, which contradicts the top-level
        # {error_code, message, severity, fix_hint} envelope the 500 handler emits and the
        # frontend parses. Lift dict details to the top level so there is exactly one shape.
        detail = error.detail
        if isinstance(detail, dict):
            body = {"severity": "BLOCKING", "fix_hint": "", **detail}
            body.setdefault("error_code", "REQUEST_FAILED")
            body.setdefault("message", "Request failed.")
        else:
            body = {
                "error_code": "REQUEST_FAILED",
                "message": str(detail),
                "severity": "BLOCKING",
                "fix_hint": "",
            }
        body["request_id"] = request.headers.get("X-Request-ID")
        return JSONResponse(status_code=error.status_code, content=body, headers=getattr(error, "headers", None))

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, error: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "REQUEST_INVALID",
                "message": "The request body or query string failed schema validation.",
                "severity": "BLOCKING",
                "fix_hint": "Check the reported fields against the OpenAPI schema at /api/v1/openapi.json.",
                "findings": [
                    {
                        "error_code": "REQUEST_FIELD_INVALID",
                        "severity": "BLOCKING",
                        "message": item.get("msg", ""),
                        "fix_hint": "",
                        "field": ".".join(str(part) for part in item.get("loc", ())),
                        "row": None,
                        "entity_id": None,
                    }
                    for item in error.errors()
                ],
                "request_id": request.headers.get("X-Request-ID"),
            },
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        return JSONResponse(
            status_code=500,
            content={"error_code": "INTERNAL_ERROR", "message": "Unexpected server error.", "severity": "BLOCKING", "fix_hint": "Use the request ID to inspect server logs.", "request_id": request.headers.get("X-Request-ID")},
        )

    return application


app = create_app()
