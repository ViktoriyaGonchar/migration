"""Уведомления администраторам в Telegram после создания заявки на оплату (Phase 5)."""

from __future__ import annotations

import logging

from aiogram import Bot

from bot.config import BotSettings

_log = logging.getLogger(__name__)


async def notify_admins_manual_payment(
    bot: Bot,
    settings: BotSettings,
    *,
    request_id: int,
    telegram_user_id: int,
    subscriber_id: int | None,
) -> None:
    """Рассылает уведомление только о новой заявке (без спама при повторном «Я оплатил»)."""
    if not settings.admin_notify_telegram_ids:
        return
    sub_part = f"subscriber_id={subscriber_id}" if subscriber_id is not None else "подписчик не привязан"
    text = (
        f"Новая заявка на оплату #{request_id}.\n"
        f"Telegram user: {telegram_user_id}\n"
        f"{sub_part}\n"
        f"Проверьте перевод и при необходимости выдайте доступ в /admin → Оператор."
    )
    for chat_id in settings.admin_notify_telegram_ids:
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            # Phase 9: явные поля для grep/агрегации логов (без секретов).
            _log.exception(
                "admin_notify_manual_payment_failed request_id=%s telegram_user_id=%s "
                "subscriber_id=%s admin_chat_id=%s",
                request_id,
                telegram_user_id,
                subscriber_id,
                chat_id,
            )
