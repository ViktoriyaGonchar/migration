"""
Единая выдача доступа (подписка + login token + URL) для CLI и будущих каналов (бот).

Не содержит consume и не трогает сессии браузера — только доменная логика выдачи.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.subscriber import Subscriber
from app.db.models.subscription import Subscription
from app.services import audit as audit_service
from app.services.login_tokens import create_login_token_for_subscriber
from app.services.subscriptions import get_active_subscription_for_subscriber
from app.util.timeutil import as_utc

# Источник подписки и meta.channel в audit (ручной CLI у сервера).
CHANNEL_MANUAL_CLI = "manual_cli"
# Phase 2B: канал Telegram / internal API (без хранения telegram user id в audit).
CHANNEL_TELEGRAM = "telegram"
# Phase 4: действия из web-интерфейса оператора в SQLAdmin.
CHANNEL_ADMIN_UI = "admin_ui"
ACTOR_CLI = "operator"
# Внутренний вызов (бот через HTTP), не конкретный человек.
ACTOR_INTERNAL = "system"
# Залогиненный администратор (операторский UI).
ACTOR_ADMIN = "admin"


async def require_subscriber_exists(db: AsyncSession, subscriber_id: int) -> None:
    """Явная проверка FK: иначе SQLite даст IntegrityError, а reissue — неверное сообщение."""
    row = await db.get(Subscriber, subscriber_id)
    if row is None:
        raise ValueError("Подписчик не найден")


def format_login_url(*, raw_token: str, settings: Settings) -> str:
    """Собирает публичный URL consume; сырой token только для печати оператору."""
    base = settings.base_url.rstrip("/")
    return f"{base}/auth/login?token={raw_token}"


async def upsert_subscription_days(
    db: AsyncSession,
    subscriber_id: int,
    days: int,
    *,
    source: str | None,
) -> tuple[Subscription, Literal["created", "extended"]]:
    """
    MVP: одна активная подписка — при продлении обновляем ends_at той же строки;
    если активной нет — создаём новую запись (история истёкших строк может оставаться в БД).
    """
    if days < 1:
        raise ValueError("Число дней должно быть >= 1")

    await require_subscriber_exists(db, subscriber_id)

    now = datetime.now(timezone.utc)
    active = await get_active_subscription_for_subscriber(db, subscriber_id)

    if active is not None:
        new_end = as_utc(active.ends_at) + timedelta(days=days)
        active.ends_at = new_end
        if source is not None:
            active.source = source
        await db.flush()
        return active, "extended"

    ends = now + timedelta(days=days)
    row = Subscription(
        subscriber_id=subscriber_id,
        status="active",
        starts_at=now,
        ends_at=ends,
        source=source,
    )
    db.add(row)
    await db.flush()
    return row, "created"


async def _write_grant_or_extend_audit(
    db: AsyncSession,
    *,
    event_kind: Literal["created", "extended"],
    subscriber_id: int,
    subscription_id: int,
    days: int | None,
    login_token_id: int | None,
    channel: str,
    actor_type: str,
    extra: dict | None = None,
) -> None:
    """Общий helper аудита без секретов."""
    event = "access_granted" if event_kind == "created" else "access_extended"
    meta: dict = {
        "channel": channel,
        "subscriber_id": subscriber_id,
        "subscription_id": subscription_id,
    }
    if days is not None:
        meta["days"] = days
    if login_token_id is not None:
        meta["login_token_id"] = login_token_id
    if extra:
        meta.update(extra)
    await audit_service.write_audit(
        db,
        event_type=event,
        actor_type=actor_type,
        subject_type="subscriber",
        subject_id=subscriber_id,
        meta=meta,
    )


async def grant_access_for_days(
    db: AsyncSession,
    subscriber_id: int,
    days: int,
    settings: Settings,
    *,
    channel: str = CHANNEL_MANUAL_CLI,
    subscription_source: str | None = None,
    actor_type: str = ACTOR_CLI,
) -> str:
    """
    Продлевает или создаёт подписку, создаёт login token, пишет audit, возвращает готовый URL.
    """
    sub_source = subscription_source if subscription_source is not None else channel
    sub, kind = await upsert_subscription_days(
        db,
        subscriber_id,
        days,
        source=sub_source,
    )
    raw = secrets.token_urlsafe(32)
    lt = await create_login_token_for_subscriber(
        db,
        subscriber_id=subscriber_id,
        raw_token=raw,
        settings=settings,
    )
    await _write_grant_or_extend_audit(
        db,
        event_kind=kind,
        subscriber_id=subscriber_id,
        subscription_id=sub.id,
        days=days,
        login_token_id=lt.id,
        channel=channel,
        actor_type=actor_type,
    )
    return format_login_url(raw_token=raw, settings=settings)


async def reissue_login_link(
    db: AsyncSession,
    subscriber_id: int,
    settings: Settings,
    *,
    channel: str = CHANNEL_MANUAL_CLI,
    actor_type: str = ACTOR_CLI,
) -> str:
    """
    Новая login-ссылка при уже активной подписке; срок подписки не меняется.
    """
    await require_subscriber_exists(db, subscriber_id)
    sub = await get_active_subscription_for_subscriber(db, subscriber_id)
    if sub is None:
        raise ValueError("Нет активной подписки — сначала grant-access")

    raw = secrets.token_urlsafe(32)
    lt = await create_login_token_for_subscriber(
        db,
        subscriber_id=subscriber_id,
        raw_token=raw,
        settings=settings,
    )
    await audit_service.write_audit(
        db,
        event_type="access_link_reissued",
        actor_type=actor_type,
        subject_type="subscriber",
        subject_id=subscriber_id,
        meta={
            "channel": channel,
            "subscriber_id": subscriber_id,
            "subscription_id": sub.id,
            "login_token_id": lt.id,
        },
    )
    return format_login_url(raw_token=raw, settings=settings)


async def create_or_extend_subscription_only(
    db: AsyncSession,
    subscriber_id: int,
    days: int,
    *,
    source: str | None = CHANNEL_MANUAL_CLI,
    audit_channel: str = CHANNEL_MANUAL_CLI,
    audit_actor_type: str = ACTOR_CLI,
) -> tuple[Subscription, Literal["created", "extended"]]:
    """
    Только подписка + audit (без token). Для совместимости команды create-subscription.
    """
    sub, kind = await upsert_subscription_days(db, subscriber_id, days, source=source)
    await _write_grant_or_extend_audit(
        db,
        event_kind=kind,
        subscriber_id=subscriber_id,
        subscription_id=sub.id,
        days=days,
        login_token_id=None,
        channel=audit_channel,
        actor_type=audit_actor_type,
        extra={"command": "create_subscription"},
    )
    return sub, kind


async def legacy_issue_login_token_url(
    db: AsyncSession,
    subscriber_id: int,
    settings: Settings,
) -> str:
    """
    Совместимость с issue-login-token: только новый token + URL, без проверки подписки и без audit.
    """
    await require_subscriber_exists(db, subscriber_id)
    raw = secrets.token_urlsafe(32)
    await create_login_token_for_subscriber(
        db,
        subscriber_id=subscriber_id,
        raw_token=raw,
        settings=settings,
    )
    return format_login_url(raw_token=raw, settings=settings)
