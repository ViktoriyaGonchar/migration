"""
Маршруты входа/выхода пользователя сайта.
Не логировать query string и не сохранять сырое значение token.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.deps import get_db
from app.services import audit as audit_service
from app.services.auth_consume import consume_login_token_create_session
from app.services.web_sessions import revoke_session_by_raw_token
from app.util.timeutil import as_utc

router = APIRouter(tags=["auth"])


@router.get("/auth/login")
async def auth_login(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    token: str | None = None,
) -> RedirectResponse:
    """Обмен одноразового login token на новую пользовательскую сессию (всегда новый session id)."""
    if not token:
        raise HTTPException(status_code=400, detail="Отсутствует параметр token")

    try:
        raw_session, expires_at = await consume_login_token_create_session(
            db,
            raw_login_token=token,
            settings=settings,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    now = datetime.now(timezone.utc)
    max_age = max(60, int((as_utc(expires_at) - now).total_seconds()))

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=settings.user_session_cookie_name,
        value=raw_session,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Явная инвалидация server-side сессии и очистка cookie."""
    raw = request.cookies.get(settings.user_session_cookie_name)
    if raw:
        await revoke_session_by_raw_token(db, raw_token=raw, settings=settings)
        await audit_service.write_audit(
            db,
            event_type="user_logout",
            actor_type="user",
            meta={"revoked": True},
        )
        await db.commit()

    response = RedirectResponse(url="/", status_code=302)
    # Те же атрибуты, что при set_cookie — иначе браузер может не удалить cookie.
    response.delete_cookie(
        key=settings.user_session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
