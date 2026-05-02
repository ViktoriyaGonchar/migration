"""Точка входа ASGI: health, публичные /assets, auth, закрытый /, SQLAdmin."""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.admin.setup import init_sqladmin
from app.api.auth import router as auth_router
from app.api.internal.router import router as internal_router
from app.config import get_settings
from app.web.site import router as site_router

_internal_api_log = logging.getLogger("app.internal_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Резерв под будущие startup/shutdown (БД только через Alembic)."""
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="Migration Compass", lifespan=lifespan)

    @application.middleware("http")
    async def log_internal_api_requests(request: Request, call_next):
        """Phase 9: operational-лог только для префикса /api/internal (сайт и /admin не трогаем)."""
        if not request.url.path.startswith("/api/internal"):
            return await call_next(request)
        request_id = str(uuid.uuid4())
        # Для обработчиков internal: при необходимости читать getattr(request.state, "internal_request_id", None)
        request.state.internal_request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            _internal_api_log.exception(
                "internal_api_request_failed request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        _internal_api_log.info(
            "internal_api_request method=%s path=%s status_code=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            request_id,
        )
        return response

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    assets_dir = (settings.site_root.resolve() / "assets")
    if assets_dir.is_dir():
        application.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="assets",
        )

    application.include_router(auth_router)
    application.include_router(internal_router)
    application.include_router(site_router)
    init_sqladmin(application, settings)
    return application


app = create_app()
