"""
Привязка Telegram user_id к подписчику: одноразовые deep-link токены и постоянные связи.

Не логировать сырой token; в audit не писать профиль Telegram (username и т.д.).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.telegram_link_token import TelegramLinkToken
from app.db.models.telegram_subscriber_link import TelegramSubscriberLink
from app.services import audit as audit_service
from app.services.access_issue import CHANNEL_MANUAL_CLI, CHANNEL_TELEGRAM, ACTOR_CLI, ACTOR_INTERNAL
from app.services.access_issue import require_subscriber_exists
from app.services.security import hash_token

# Единый текст для неверного/просроченного/использованного токена (для API detail).
LINK_INVALID_MESSAGE = "Ссылка недействительна"


class LinkInvalidError(Exception):
    """Токен не найден, истёк или уже использован."""


class LinkConflictError(Exception):
    """Конфликт уникальности привязки (409)."""


async def invalidate_pending_tokens_for_subscriber(db: AsyncSession, subscriber_id: int) -> None:
    """Удаляет все неиспользованные pending-токены подписчика перед выдачей нового."""
    await db.execute(
        delete(TelegramLinkToken).where(
            TelegramLinkToken.subscriber_id == subscriber_id,
            TelegramLinkToken.used_at.is_(None),
        )
    )


async def issue_telegram_link_token(
    db: AsyncSession,
    subscriber_id: int,
    settings: Settings,
    *,
    ttl_hours: int,
    audit_channel: str = CHANNEL_MANUAL_CLI,
    audit_actor_type: str = ACTOR_CLI,
) -> str:
    """
    Создаёт новый токен привязки; инвалидирует старые pending.
    Возвращает сырой token один раз (для CLI/UI — только печать, не логировать).
    audit_channel / audit_actor_type: CLI по умолчанию manual_cli/operator; UI — admin_ui/admin.
    """
    if ttl_hours < 1:
        raise ValueError("ttl_hours должен быть >= 1")
    await require_subscriber_exists(db, subscriber_id)
    await invalidate_pending_tokens_for_subscriber(db, subscriber_id)

    raw = secrets.token_urlsafe(32)
    if len(raw) > 64:
        raw = raw[:64]

    th = hash_token(raw, settings.token_pepper)
    now = datetime.now(timezone.utc)
    row = TelegramLinkToken(
        subscriber_id=subscriber_id,
        token_hash=th,
        expires_at=now + timedelta(hours=ttl_hours),
    )
    db.add(row)
    await db.flush()

    await audit_service.write_audit(
        db,
        event_type="telegram_link_token_issued",
        actor_type=audit_actor_type,
        subject_type="subscriber",
        subject_id=subscriber_id,
        meta={
            "channel": audit_channel,
            "subscriber_id": subscriber_id,
            "telegram_link_token_id": row.id,
            "ttl_hours": ttl_hours,
        },
    )
    return raw


async def consume_telegram_link(
    db: AsyncSession,
    *,
    raw_token: str,
    telegram_user_id: int,
    settings: Settings,
) -> int:
    """
    Проверяет токен, создаёт привязку при отсутствии конфликтов, помечает токен использованным.
    Возвращает subscriber_id.

    Гонка двух параллельных consume одного токена: сначала атомарный UPDATE used_at
    (только если ещё NULL и не истёк срок); при 0 строк — «недействительна». При 409 откат снимает used_at.
    """
    if not raw_token or not raw_token.strip():
        raise LinkInvalidError()
    now = datetime.now(timezone.utc)
    th = hash_token(raw_token.strip(), settings.token_pepper)

    claim = (
        update(TelegramLinkToken)
        .where(
            TelegramLinkToken.token_hash == th,
            TelegramLinkToken.used_at.is_(None),
            TelegramLinkToken.expires_at >= now,
        )
        .values(used_at=now)
        .returning(TelegramLinkToken.subscriber_id)
    )
    res_claim = await db.execute(claim)
    subscriber_id = res_claim.scalar_one_or_none()
    if subscriber_id is None:
        raise LinkInvalidError()

    res_sub = await db.execute(
        select(TelegramSubscriberLink).where(TelegramSubscriberLink.subscriber_id == subscriber_id)
    )
    link_for_sub = res_sub.scalar_one_or_none()

    res_tg = await db.execute(
        select(TelegramSubscriberLink).where(TelegramSubscriberLink.telegram_user_id == telegram_user_id)
    )
    link_for_tg = res_tg.scalar_one_or_none()

    if link_for_sub is not None and link_for_sub.telegram_user_id != telegram_user_id:
        raise LinkConflictError("Подписчик уже привязан к другому Telegram-аккаунту")

    if link_for_tg is not None and link_for_tg.subscriber_id != subscriber_id:
        raise LinkConflictError("Этот Telegram уже привязан к другому подписчику")

    created_new = False
    if link_for_sub is None:
        db.add(
            TelegramSubscriberLink(
                subscriber_id=subscriber_id,
                telegram_user_id=telegram_user_id,
            )
        )
        created_new = True

    await db.flush()

    if created_new:
        await audit_service.write_audit(
            db,
            event_type="telegram_linked",
            actor_type=ACTOR_INTERNAL,
            subject_type="subscriber",
            subject_id=subscriber_id,
            meta={
                "channel": CHANNEL_TELEGRAM,
                "subscriber_id": subscriber_id,
                "telegram_user_id": telegram_user_id,
            },
        )

    return subscriber_id


async def resolve_subscriber_id_by_telegram(db: AsyncSession, telegram_user_id: int) -> int | None:
    """Возвращает subscriber_id или None, если привязки нет."""
    result = await db.execute(
        select(TelegramSubscriberLink.subscriber_id).where(
            TelegramSubscriberLink.telegram_user_id == telegram_user_id
        )
    )
    row = result.scalar_one_or_none()
    return int(row) if row is not None else None


async def get_telegram_user_id_for_subscriber(db: AsyncSession, subscriber_id: int) -> int | None:
    """Текущий telegram_user_id для подписчика или None, если привязки нет."""
    result = await db.execute(
        select(TelegramSubscriberLink.telegram_user_id).where(
            TelegramSubscriberLink.subscriber_id == subscriber_id
        )
    )
    row = result.scalar_one_or_none()
    return int(row) if row is not None else None


async def unlink_subscriber(
    db: AsyncSession,
    subscriber_id: int,
    *,
    audit_channel: str = CHANNEL_MANUAL_CLI,
    audit_actor_type: str = ACTOR_CLI,
) -> bool:
    """Снимает привязку по subscriber_id. Возвращает True, если запись была."""
    await require_subscriber_exists(db, subscriber_id)
    result = await db.execute(
        select(TelegramSubscriberLink).where(TelegramSubscriberLink.subscriber_id == subscriber_id)
    )
    link = result.scalar_one_or_none()
    if link is None:
        return False
    tg_id = link.telegram_user_id
    db.delete(link)
    await db.flush()
    await audit_service.write_audit(
        db,
        event_type="telegram_unlinked",
        actor_type=audit_actor_type,
        subject_type="subscriber",
        subject_id=subscriber_id,
        meta={
            "channel": audit_channel,
            "subscriber_id": subscriber_id,
            "telegram_user_id": tg_id,
        },
    )
    return True


async def unlink_telegram_user(db: AsyncSession, telegram_user_id: int) -> bool:
    """Снимает привязку по telegram_user_id. Возвращает True, если запись была."""
    result = await db.execute(
        select(TelegramSubscriberLink).where(TelegramSubscriberLink.telegram_user_id == telegram_user_id)
    )
    link = result.scalar_one_or_none()
    if link is None:
        return False
    sid = link.subscriber_id
    db.delete(link)
    await db.flush()
    await audit_service.write_audit(
        db,
        event_type="telegram_unlinked",
        actor_type=ACTOR_CLI,
        subject_type="subscriber",
        subject_id=sid,
        meta={
            "channel": CHANNEL_MANUAL_CLI,
            "subscriber_id": sid,
            "telegram_user_id": telegram_user_id,
        },
    )
    return True
