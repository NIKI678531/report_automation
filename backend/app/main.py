from fastapi import FastAPI, Request
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

    @application.exception_handler(Exception)
    async def unexpected_error(_: Request, error: Exception):
        return JSONResponse(
            status_code=500,
            content={"error_code": "INTERNAL_ERROR", "message": "Unexpected server error.", "severity": "BLOCKING", "fix_hint": "Use the request ID to inspect server logs."},
        )

    return application


app = create_app()
