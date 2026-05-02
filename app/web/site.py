"""Закрытая главная страница: только существующий index.html с диска (без Jinja)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.db.models.subscription import Subscription
from app.db.models.web_session import WebSession
from app.deps import require_gated_site_access

router = APIRouter(tags=["site"])


@router.get("/")
async def gated_index(
    _access: Annotated[tuple[WebSession, Subscription], Depends(require_gated_site_access)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    """Отдаёт корневой index.html только при валидной пользовательской сессии и подписке."""
    path = (settings.site_root.resolve() / "index.html")
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Файл index.html недоступен")
    return FileResponse(path, media_type="text/html; charset=utf-8")
