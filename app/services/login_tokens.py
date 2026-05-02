"""Создание записи login_token (только хэш в БД)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.login_token import LoginToken
from app.services.security import hash_token


async def create_login_token_for_subscriber(
    db: AsyncSession,
    *,
    subscriber_id: int,
    raw_token: str,
    settings: Settings,
    ttl_minutes: int = 15,
) -> LoginToken:
    """Сохраняет хэш одноразового токена; raw_token показывается вызывающему только один раз (CLI)."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ttl_minutes)
    th = hash_token(raw_token, settings.token_pepper)
    row = LoginToken(
        subscriber_id=subscriber_id,
        token_hash=th,
        expires_at=expires,
    )
    db.add(row)
    await db.flush()
    return row
