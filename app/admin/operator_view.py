"""
Страница оператора в SQLAdmin: выдача доступа и Telegram-привязка без дублирования сервисов.
"""

from __future__ import annotations

import logging
from typing import Any

from sqladmin import BaseView, expose
from starlette.requests import Request

from app.config import get_settings
from app.db.models.manual_payment_request import ManualPaymentRequest
from app.db.session import async_session_maker
from app.services import access_issue
from app.services import manual_payment_requests as mpr_service
from app.services import telegram_linking
from app.services.subscriptions import get_active_subscription_for_subscriber
from app.util.timeutil import as_utc

_log = logging.getLogger(__name__)


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


async def _build_card(subscriber_id: int) -> dict[str, Any] | None:
    """Данные карточки подписчика или None, если подписчик не найден."""
    async with async_session_maker() as session:
        try:
            await access_issue.require_subscriber_exists(session, subscriber_id)
        except ValueError:
            return None
        sub = await get_active_subscription_for_subscriber(session, subscriber_id)
        tg = await telegram_linking.get_telegram_user_id_for_subscriber(session, subscriber_id)
        return {
            "subscriber_id": subscriber_id,
            "subscription_active": sub is not None,
            "ends_at": as_utc(sub.ends_at).isoformat() if sub else None,
            "telegram_user_id": tg,
        }


class OperatorView(BaseView):
    """Одна страница: поиск по subscriber_id, статус, выдача, reissue, Telegram, unlink."""

    name = "Оператор"
    name_plural = "Оператор"
    icon = "fa-solid fa-user-gear"

    @expose("/operator", methods=["GET", "POST"], identity="operator")
    async def operator_page(self, request: Request):
        settings = get_settings()
        title = "Оператор"
        subtitle = "Выдача доступа и привязка Telegram"
        error_message: str | None = None
        result_login_url: str | None = None
        result_telegram_deep_link: str | None = None
        result_success: str | None = None
        subscriber_id: int | None = _parse_int(request.query_params.get("subscriber_id"))
        card: dict[str, Any] | None = None
        manual_pending: ManualPaymentRequest | None = None
        manual_recent: list[ManualPaymentRequest] = []
        days_default = 30
        ttl_hours_default = 72

        if request.method == "POST":
            form = await request.form()
            action = str(form.get("action") or "").strip()
            sid = _parse_int(form.get("subscriber_id"))

            if action == "load":
                if sid is None:
                    subscriber_id = None
                    error_message = "Укажите корректный ID подписчика."
                else:
                    subscriber_id = sid
            elif sid is None:
                error_message = "Не указан подписчик."
            else:
                subscriber_id = sid
                async with async_session_maker() as session:
                    try:
                        if action == "grant":
                            days = _parse_int(form.get("days"))
                            if days is None or days < 1:
                                error_message = "Укажите число дней (не меньше 1)."
                            else:
                                result_login_url = await access_issue.grant_access_for_days(
                                    session,
                                    sid,
                                    days,
                                    settings,
                                    channel=access_issue.CHANNEL_ADMIN_UI,
                                    subscription_source=access_issue.CHANNEL_ADMIN_UI,
                                    actor_type=access_issue.ACTOR_ADMIN,
                                )
                                await session.commit()
                                result_success = "Доступ выдан или продлён."
                        elif action == "reissue":
                            result_login_url = await access_issue.reissue_login_link(
                                session,
                                sid,
                                settings,
                                channel=access_issue.CHANNEL_ADMIN_UI,
                                actor_type=access_issue.ACTOR_ADMIN,
                            )
                            await session.commit()
                            result_success = "Ссылка для входа создана."
                        elif action == "telegram_link":
                            if not settings.bot_username:
                                error_message = (
                                    "Задайте BOT_USERNAME в .env для генерации ссылки привязки."
                                )
                            else:
                                ttl = _parse_int(form.get("ttl_hours"))
                                if ttl is None or ttl < 1:
                                    ttl = ttl_hours_default
                                raw = await telegram_linking.issue_telegram_link_token(
                                    session,
                                    sid,
                                    settings,
                                    ttl_hours=ttl,
                                    audit_channel=access_issue.CHANNEL_ADMIN_UI,
                                    audit_actor_type=access_issue.ACTOR_ADMIN,
                                )
                                await session.commit()
                                result_telegram_deep_link = (
                                    f"https://t.me/{settings.bot_username}?start={raw}"
                                )
                                result_success = "Ссылка привязки Telegram создана."
                        elif action == "unlink":
                            ok = await telegram_linking.unlink_subscriber(
                                session,
                                sid,
                                audit_channel=access_issue.CHANNEL_ADMIN_UI,
                                audit_actor_type=access_issue.ACTOR_ADMIN,
                            )
                            await session.commit()
                            if ok:
                                result_success = "Привязка Telegram снята."
                            else:
                                error_message = "Привязки Telegram не было."
                        else:
                            error_message = "Неизвестное действие."
                    except ValueError as e:
                        await session.rollback()
                        error_message = str(e)
                    except Exception:
                        await session.rollback()
                        _log.exception("operator_page")
                        error_message = "Операция не выполнена. Попробуйте снова."

        if subscriber_id is not None:
            card = await _build_card(subscriber_id)
            if card is None and error_message is None:
                error_message = "Подписчик не найден."
            elif card is not None:
                async with async_session_maker() as session:
                    manual_pending = await mpr_service.get_latest_pending_manual_payment_request_for_subscriber(
                        session, subscriber_id
                    )
                    manual_recent = await mpr_service.list_recent_manual_payment_requests_for_subscriber(
                        session, subscriber_id, limit=10
                    )
                    await session.commit()
        else:
            card = None

        context = {
            "request": request,
            "title": title,
            "subtitle": subtitle,
            "subscriber_id": subscriber_id,
            "card": card,
            "manual_pending": manual_pending,
            "manual_recent": manual_recent,
            "error_message": error_message,
            "result_login_url": result_login_url,
            "result_telegram_deep_link": result_telegram_deep_link,
            "result_success": result_success,
            "days_default": days_default,
            "ttl_hours_default": ttl_hours_default,
            "as_utc": as_utc,
        }
        return await self.templates.TemplateResponse(
            request,
            "admin/operator.html",
            context,
        )
