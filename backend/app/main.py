import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import entra
from app.core.config import ConfigurationError, settings
from app.core.security import AuthorizationMiddleware


logger = logging.getLogger("uvicorn.error")


def _verify_deployment_configuration() -> None:
    """Refuse to start a deployed process that is configured unsafely.

    These are the settings whose defaults are only sound on a workstation - a public signing
    secret, header-asserted identity, the fixture lane. Discovering them in production means they
    were already used, so the check runs before the first request rather than at first use.
    """
    problems = settings.deployment_problems()
    if problems:
        for problem in problems:
            logger.error("Refusing to start: %s", problem)
        raise ConfigurationError(
            f"{len(problems)} unsafe setting(s) for AUTH_MODE={settings.auth_mode}: " + " ".join(problems)
        )
    if settings.auth_mode == "ENTRA":
        # A missing PyJWT would otherwise surface as a 500 on the first authenticated request,
        # i.e. after the service had already been declared healthy.
        entra.ensure_available()


def create_app() -> FastAPI:
    _verify_deployment_configuration()
    # Imported here, not at module scope, so the guard above is genuinely the first thing that
    # runs. `app.api.routes` pulls in the object-storage backend, which raises on a STORAGE_BACKEND
    # nothing implements - as a module-level import that error arrived before the guard could
    # report the rest of the configuration alongside it.
    from app.api.routes import router

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url="/docs",
    )
    # Authorization is added first so CORS ends up outermost: a browser client must be able to read
    # a 401/403 envelope, and a response without CORS headers is reported as an opaque network
    # failure instead.
    application.add_middleware(AuthorizationMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
        request_id = request.headers.get("X-Request-ID")
        logger.error(
            "Unexpected request error request_id=%s method=%s path=%s",
            request_id or "-",
            request.method,
            request.url.path,
            exc_info=(type(error), error, error.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content={"error_code": "INTERNAL_ERROR", "message": "Unexpected server error.", "severity": "BLOCKING", "fix_hint": "Use the request ID to inspect server logs.", "request_id": request_id},
        )

    return application


app = create_app()
