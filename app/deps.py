"""Зависимости FastAPI: БД и проверка доступа к закрытому сайту."""

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import async_session_maker
from app.db.models.web_session import WebSession
from app.db.models.subscription import Subscription
from app.services.subscriptions import get_active_subscription_for_subscriber
from app.services.web_sessions import find_valid_session_by_raw_token

_log = logging.getLogger(__name__)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Сессия БД на запрос; commit выполняет маршрут при успехе."""
    async with async_session_maker() as session:
        try:
            yield session
        except OperationalError as exc:
            # Только типичные сообщения SQLite о блокировке (без общего подстрочного "locked").
            msg = str(getattr(exc, "orig", None) or exc).lower()
            if "database is locked" in msg or "database table is locked" in msg:
                _log.warning(
                    "sqlite_operational_error context=get_db hint=database_may_be_locked",
                    exc_info=True,
                )
            raise


async def require_gated_site_access(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> tuple[WebSession, Subscription]:
    """
    Валидная пользовательская cookie + неотозванная сессия + активная подписка.
    Админская сессия Starlette здесь не используется.
    """
    raw = request.cookies.get(settings.user_session_cookie_name)
    if not raw:
        raise HTTPException(status_code=401, detail="Требуется вход")

    ws = await find_valid_session_by_raw_token(db, raw_token=raw, settings=settings)
    if ws is None:
        raise HTTPException(status_code=401, detail="Сессия недействительна или истекла")

    sub = await get_active_subscription_for_subscriber(db, ws.subscriber_id)
    if sub is None:
        raise HTTPException(status_code=403, detail="Подписка не активна")

    return ws, sub
