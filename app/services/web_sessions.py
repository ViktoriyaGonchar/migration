"""Создание и отзыв пользовательских веб-сессий (отдельно от админской сессии Starlette)."""

import secrets
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.web_session import WebSession
from app.services.security import hash_token
from app.util.timeutil import as_utc


def new_raw_session_token() -> str:
    """Новый непредсказуемый opaque-токен для cookie (никогда не переиспользовать старый)."""
    return secrets.token_urlsafe(32)


async def find_valid_session_by_raw_token(
    db: AsyncSession,
    *,
    raw_token: str,
    settings: Settings,
) -> WebSession | None:
    """Активная сессия: не revoked, не истекла (expires_at в UTC)."""
    th = hash_token(raw_token, settings.token_pepper)
    now = datetime.now(timezone.utc)
    stmt = select(WebSession).where(WebSession.token_hash == th, WebSession.revoked_at.is_(None))
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if as_utc(row.expires_at) <= now:
        return None
    return row


async def revoke_session_by_raw_token(
    db: AsyncSession,
    *,
    raw_token: str,
    settings: Settings,
) -> bool:
    """Инвалидация сессии по значению из cookie; True если строка была найдена и обновлена."""
    th = hash_token(raw_token, settings.token_pepper)
    now = datetime.now(timezone.utc)
    stmt = (
        update(WebSession)
        .where(
            WebSession.token_hash == th,
            WebSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    res = await db.execute(stmt)
    return res.rowcount > 0
