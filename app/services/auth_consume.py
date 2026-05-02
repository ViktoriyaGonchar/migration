"""
Атомарное поглощение login token и создание НОВОЙ пользовательской сессии.

SQLite: вместо SELECT FOR UPDATE используем одну условную UPDATE с RETURNING —
ровно одно соединение «выигрывает» гонку; повторный consume того же токена не проходит.
"""

from datetime import datetime, timezone
from typing import NoReturn

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.login_token import LoginToken
from app.db.models.web_session import WebSession
from app.services import audit as audit_service
from app.services.security import hash_token
from app.services.subscriptions import get_active_subscription_for_subscriber
from app.services.web_sessions import new_raw_session_token
from app.util.timeutil import as_utc


async def consume_login_token_create_session(
    db: AsyncSession,
    *,
    raw_login_token: str,
    settings: Settings,
) -> tuple[str, datetime]:
    """
    (сырое значение для cookie пользователя, expires_at новой сессии).
    Commit выполняет вызывающий маршрут.
    """
    now = datetime.now(timezone.utc)
    token_hash = hash_token(raw_login_token, settings.token_pepper)

    # Одна атомарная операция: пометить использованным только если ещё не used и не просрочен.
    # RETURNING (SQLite 3.35+): идентификаторы без повторного чтения по хэшу в гонке.
    upd = (
        update(LoginToken)
        .where(
            LoginToken.token_hash == token_hash,
            LoginToken.used_at.is_(None),
            LoginToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(LoginToken.id, LoginToken.subscriber_id)
    )
    result = await db.execute(upd)
    row = result.fetchone()

    if row is None:
        await _audit_consume_failure_and_raise(db, token_hash=token_hash, now=now)

    login_token_id = int(row[0])
    subscriber_id = int(row[1])

    sub = await get_active_subscription_for_subscriber(db, subscriber_id)
    if sub is None:
        await audit_service.write_audit(
            db,
            event_type="login_token_consume_fail",
            actor_type="user",
            subject_type="subscriber",
            subject_id=subscriber_id,
            meta={"reason": "no_active_subscription", "login_token_id": login_token_id},
        )
        raise HTTPException(status_code=403, detail="Нет активной подписки")

    raw_session = new_raw_session_token()
    session_hash = hash_token(raw_session, settings.token_pepper)
    ws = WebSession(
        subscriber_id=subscriber_id,
        token_hash=session_hash,
        expires_at=sub.ends_at,
    )
    db.add(ws)
    await db.flush()

    await audit_service.write_audit(
        db,
        event_type="login_token_consumed_session_created",
        actor_type="user",
        subject_type="subscriber",
        subject_id=subscriber_id,
        meta={"login_token_id": login_token_id, "web_session_id": ws.id},
    )

    return raw_session, ws.expires_at


async def _audit_consume_failure_and_raise(
    db: AsyncSession,
    *,
    token_hash: bytes,
    now: datetime,
) -> NoReturn:
    """Диагностика без утечки секрета: в meta только reason и id, не хэш и не токен."""
    r = await db.execute(select(LoginToken).where(LoginToken.token_hash == token_hash))
    lt = r.scalar_one_or_none()
    if lt is None:
        await audit_service.write_audit(
            db,
            event_type="login_token_consume_fail",
            actor_type="user",
            subject_type="login_token",
            subject_id=None,
            meta={"reason": "not_found"},
        )
        raise HTTPException(status_code=400, detail="Недействительная ссылка входа")
    if lt.used_at is not None:
        await audit_service.write_audit(
            db,
            event_type="login_token_consume_fail",
            actor_type="user",
            subject_type="login_token",
            subject_id=lt.id,
            meta={"reason": "already_used"},
        )
        raise HTTPException(status_code=400, detail="Ссылка входа уже использована")
    if as_utc(lt.expires_at) <= now:
        await audit_service.write_audit(
            db,
            event_type="login_token_consume_fail",
            actor_type="user",
            subject_type="login_token",
            subject_id=lt.id,
            meta={"reason": "expired"},
        )
        raise HTTPException(status_code=400, detail="Срок ссылки входа истёк")
    # Несогласованное состояние (например, гонка по времени сравнения в SQL vs Python).
    await audit_service.write_audit(
        db,
        event_type="login_token_consume_fail",
        actor_type="user",
        subject_type="login_token",
        subject_id=lt.id,
        meta={"reason": "claim_race_or_db_inconsistency"},
    )
    raise HTTPException(status_code=400, detail="Недействительная ссылка входа")
