"""Команды бота: internal API, привязка через /start <token> (Phase 3), оплата (Phase 5)."""

import logging
from html import escape as html_escape

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.payments.stub_adapters import known_providers

from bot.client import InternalApiClient
from bot.config import BotSettings
from bot.notify import notify_admins_manual_payment

router = Router()
_log = logging.getLogger(__name__)

# Callback data для кнопки «Я оплатил» (без состояния FSM).
PAY_CALLBACK_DATA = "manual_pay_confirmed"
# Короткий префикс для inline callback (лимит Telegram 64 байта на callback_data).
STUB_CALLBACK_PREFIX = "ps:"

_STUB_BUTTON_LABELS = {
    "manual_card": "Stub: карта",
    "telegram_stub": "Stub: Telegram",
    "yookassa_stub": "Stub: ЮKassa",
    "wise_stub": "Stub: Wise",
    "payoneer_stub": "Stub: Payoneer",
}

_MSG_SERVER_UNAVAILABLE = "Сервер временно недоступен. Попробуйте позже."
_MSG_LINK_FAILED = "Не удалось получить ссылку. Попробуйте позже или обратитесь к администратору."
_MSG_NOT_LINKED = "Сначала привяжите Telegram по ссылке от администратора."
_MSG_LINK_INVALID = "Ссылка недействительна или уже использована."
_MSG_LINK_CONFLICT = "Привязка невозможна. Обратитесь к администратору."


def _welcome_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="/help"),
                KeyboardButton(text="/status"),
                KeyboardButton(text="/get_link"),
            ],
            [
                KeyboardButton(text="/pay"),
                KeyboardButton(text="/pay_status"),
                KeyboardButton(text="/pay_methods"),
            ],
        ],
        resize_keyboard=True,
    )


def _payment_details_text(settings: BotSettings) -> str:
    """Текст с реквизитами для перевода (из env). Сумма совпадает с snapshot в БД при том же PAYMENT_AMOUNT_LABEL у API."""
    lines = [
        "<b>/pay</b> — реальная оплата переводом (проверка оператором).",
        "Это не тестовые заглушки из /pay_methods.",
        "",
        "Оплата переводом на карту.",
        "",
    ]
    if not settings.payment_card_number.strip():
        lines.append("Реквизиты временно не настроены. Обратитесь к администратору.")
        return "\n".join(lines)
    lines.append(f"Номер карты: <code>{settings.payment_card_number.strip()}</code>")
    if settings.payment_recipient_name.strip():
        lines.append(f"Получатель: {settings.payment_recipient_name.strip()}")
    if settings.payment_bank_name.strip():
        lines.append(f"Банк: {settings.payment_bank_name.strip()}")
    if settings.payment_amount_label.strip():
        lines.append(f"Сумма / тариф: {settings.payment_amount_label.strip()}")
    lines.extend(
        [
            "",
            "После перевода нажмите кнопку «Я оплатил». Доступ выдаётся вручную после проверки.",
        ]
    )
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, api: InternalApiClient) -> None:
    """Deep link /start <token> — привязка; /start без аргумента — приветствие."""
    keyboard = _welcome_keyboard()
    if command.args:
        token = command.args.strip()
        if message.from_user is None:
            await message.answer("Нет данных пользователя.")
            return
        try:
            await api.telegram_link_consume(token, message.from_user.id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                await message.answer(_MSG_LINK_INVALID)
            elif exc.response.status_code == 409:
                await message.answer(_MSG_LINK_CONFLICT)
            else:
                _log.warning("telegram_link_consume HTTP %s", exc.response.status_code)
                await message.answer(_MSG_SERVER_UNAVAILABLE)
            await message.answer(
                "Migration Compass: ссылка на вход в закрытый сайт.\n"
                "Кнопки ниже или команды /help, /status, /get_link, /pay, /pay_methods.",
                reply_markup=keyboard,
            )
            return
        except httpx.RequestError as exc:
            _log.warning("telegram_link_consume сеть: %s", exc)
            await message.answer(_MSG_SERVER_UNAVAILABLE)
            await message.answer(
                "Migration Compass: ссылка на вход в закрытый сайт.\n"
                "Кнопки ниже или команды /help, /status, /get_link, /pay, /pay_methods.",
                reply_markup=keyboard,
            )
            return
        except Exception as exc:
            _log.exception("telegram_link_consume: %s", exc)
            await message.answer(_MSG_SERVER_UNAVAILABLE)
            await message.answer(
                "Migration Compass: ссылка на вход в закрытый сайт.\n"
                "Кнопки ниже или команды /help, /status, /get_link, /pay, /pay_methods.",
                reply_markup=keyboard,
            )
            return
        await message.answer("Telegram успешно привязан к вашему доступу.", reply_markup=keyboard)
        return

    await message.answer(
        "Migration Compass: ссылка на вход в закрытый сайт.\n"
        "Кнопки ниже или команды /help, /status, /get_link, /pay, /pay_methods.",
        reply_markup=keyboard,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "/status — есть ли активная подписка и до какой даты.\n"
        "/get_link — новая одноразовая ссылка входа, если подписка активна.\n"
        "────────\n"
        "<b>/pay</b> — реквизиты для перевода на карту и заявка оператору (ручная проверка).\n"
        "────────\n"
        "<b>/pay_methods</b> — только симуляция провайдеров Phase 7 (без списания денег); "
        "нужен PAYMENTS_STUBS_ENABLED в .env бота.\n"
        "<b>/pay_status</b> — статус последней <b>ручной</b> заявки на оплату переводом (/pay).\n"
        "<b>/payment_status</b> — только тестовые stub-попытки Phase 7; к ручной оплате не относится.\n"
        "────────\n"
        "Если подписки нет, обратитесь к администратору (ручная выдача: mc-cli grant-access)."
    )


@router.message(Command("pay_status"))
async def cmd_pay_status(message: Message, api: InternalApiClient) -> None:
    """Phase 8A: последняя manual payment request; без заметок оператора пользователю."""
    if message.from_user is None:
        await message.answer("Нет данных пользователя.")
        return
    uid = message.from_user.id
    try:
        data = await api.latest_manual_payment_for_telegram(uid)
    except httpx.HTTPStatusError as exc:
        _log.warning("latest_manual_payment HTTP %s", exc.response.status_code)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except httpx.RequestError as exc:
        _log.warning("latest_manual_payment сеть: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except Exception:
        _log.exception("latest_manual_payment")
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return

    if not data.get("has_request"):
        await message.answer(
            "Ручных заявок на оплату переводом пока не было. "
            "Оформить: команда /pay (кнопка «Я оплатил» после перевода).\n\n"
            "<i>/payment_status</i> — это только тестовые stub-платежи Phase 7, не эта очередь."
        )
        return

    snap = html_escape(str(data.get("amount_label_snapshot") or "—"))
    reviewed = data.get("reviewed_at") or "—"
    parts = [
        "<b>Ручная оплата</b> (перевод на карту, проверка оператором):",
        f"Заявка №<code>{data.get('request_id')}</code>",
        f"Статус заявки: <b>{data.get('status')}</b> (это не то же самое, что доступ к сайту).",
        f"Создана (UTC, ISO-8601): {html_escape(str(data.get('created_at') or '—'))}",
    ]
    if data.get("status") != "pending":
        parts.append(f"Проверено оператором (UTC, ISO-8601): {html_escape(str(reviewed))}")
    parts.append(f"Сумма/тариф (снимок): {snap}")
    if data.get("subscriber_id") is not None:
        parts.append(f"subscriber_id: <code>{data.get('subscriber_id')}</code>")
    parts.extend(
        [
            "",
            "Доступ к закрытому сайту и одноразовая ссылка входа выдаются <b>отдельно</b> оператором после проверки. "
            "Статус «одобрено» у заявки <b>не означает</b>, что подписка уже продлена или ссылка отправлена.",
            "",
            "Заметки оператора вам не показываются. При вопросах напишите администратору.",
            "",
            "<i>/payment_status</i> — только тестовые stub-попытки, не эта заявка.",
        ]
    )
    await message.answer("\n".join(parts))


@router.message(Command("pay_methods"))
async def cmd_pay_methods(message: Message, settings: BotSettings) -> None:
    """Тестовые «провайдеры» через payment_attempts; не заменяет /pay."""
    if not settings.payments_stubs_enabled:
        await message.answer(
            "Тестовые заглушки /pay_methods отключены. Включите PAYMENTS_STUBS_ENABLED=true в .env бота "
            "(реальные платёжные API не используются)."
        )
        return
    providers = known_providers()
    rows: list[list[InlineKeyboardButton]] = []
    row_buf: list[InlineKeyboardButton] = []
    for p in providers:
        label = _STUB_BUTTON_LABELS.get(p, p)
        row_buf.append(InlineKeyboardButton(text=label, callback_data=f"{STUB_CALLBACK_PREFIX}{p}"))
        if len(row_buf) >= 2:
            rows.append(row_buf)
            row_buf = []
    if row_buf:
        rows.append(row_buf)
    intro = (
        "<b>/pay_methods — только тест (Phase 7).</b>\n"
        "Нет списания и нет реальных платёжных шлюзов. Доступ <b>не выдаётся</b> автоматически.\n"
        "<b>/pay</b> — отдельно: перевод на карту и очередь оператора.\n\n"
        "Выберите симулируемый провайдер:"
    )
    await message.answer(intro, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith(STUB_CALLBACK_PREFIX))
async def callback_stub_payment(
    callback: CallbackQuery,
    settings: BotSettings,
    api: InternalApiClient,
) -> None:
    await callback.answer()
    if not settings.payments_stubs_enabled or callback.from_user is None or callback.message is None:
        return
    raw = callback.data or ""
    provider = raw[len(STUB_CALLBACK_PREFIX) :].strip()
    if provider not in known_providers():
        await callback.message.answer("Неизвестный провайдер.")
        return
    uid = callback.from_user.id
    try:
        data = await api.create_payment_attempt(uid, provider)
    except httpx.HTTPStatusError as exc:
        _log.warning("create_payment_attempt HTTP %s", exc.response.status_code)
        await callback.message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except httpx.RequestError as exc:
        _log.warning("create_payment_attempt сеть: %s", exc)
        await callback.message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except Exception:
        _log.exception("create_payment_attempt")
        await callback.message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    pid = data.get("id")
    meta = data.get("metadata") or {}
    lines = (meta.get("display_lines") or []) if isinstance(meta, dict) else []
    extra = "\n".join(lines) if lines else ""
    await callback.message.answer(
        f"Создана <b>тестовая</b> попытка оплаты #{pid} ({provider}).\n"
        f"Статус: {data.get('status')}\n"
        f"{extra}\n\n"
        f"Проверить: /payment_status {pid}"
    )


@router.message(Command("payment_status"))
async def cmd_payment_status(
    message: Message,
    command: CommandObject,
    settings: BotSettings,
    api: InternalApiClient,
) -> None:
    if not settings.payments_stubs_enabled:
        await message.answer("Команда отключена (PAYMENTS_STUBS_ENABLED).")
        return
    if message.from_user is None:
        await message.answer("Нет данных пользователя.")
        return
    uid = message.from_user.id
    arg = (command.args or "").strip()
    try:
        if arg:
            aid = int(arg.split()[0])
            data = await api.get_payment_attempt(aid, refresh=True)
            if int(data.get("telegram_user_id", 0)) != uid:
                await message.answer("Эта попытка принадлежит другому пользователю.")
                return
            meta = data.get("metadata") or {}
            lines = (meta.get("display_lines") or []) if isinstance(meta, dict) else []
            extra = "\n".join(lines) if lines else ""
            await message.answer(
                f"<b>Тестовая</b> попытка #{data.get('id')} ({data.get('provider')})\n"
                f"Статус: {data.get('status')}\n"
                f"provider_payment_id: <code>{data.get('provider_payment_id')}</code>\n"
                f"{extra}"
            )
        else:
            items = await api.list_payment_attempts(uid, limit=8)
            if not items:
                await message.answer("Тестовых попыток оплаты пока нет.")
                return
            parts = [
                f"#{x.get('id')} {x.get('provider')} — {x.get('status')}" for x in items
            ]
            await message.answer(
                "Последние <b>тестовые</b> попытки (Phase 7):\n"
                + "\n".join(parts)
                + "\n\nПодробнее: /payment_status и числовой id из списка (например /payment_status 12)."
            )
    except ValueError:
        await message.answer("Укажите числовой id: /payment_status 1")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await message.answer("Попытка не найдена.")
        else:
            _log.warning("payment_status HTTP %s", exc.response.status_code)
            await message.answer(_MSG_SERVER_UNAVAILABLE)
    except httpx.RequestError as exc:
        _log.warning("payment_status сеть: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
    except Exception:
        _log.exception("payment_status")
        await message.answer(_MSG_SERVER_UNAVAILABLE)


@router.message(Command("pay"))
async def cmd_pay(message: Message, settings: BotSettings) -> None:
    """Показ реквизитов и inline-кнопка подтверждения перевода."""
    text = _payment_details_text(settings)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Я оплатил", callback_data=PAY_CALLBACK_DATA)],
        ]
    )
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == PAY_CALLBACK_DATA)
async def callback_manual_paid(
    callback: CallbackQuery,
    settings: BotSettings,
    api: InternalApiClient,
) -> None:
    """Создание pending-заявки через internal API и уведомление админов из бота."""
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return
    uid = callback.from_user.id
    try:
        data = await api.create_manual_payment_request(uid, None)
    except httpx.HTTPStatusError as exc:
        _log.warning("manual_payment_request HTTP %s", exc.response.status_code)
        await callback.message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except httpx.RequestError as exc:
        _log.warning("manual_payment_request сеть: %s", exc)
        await callback.message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except Exception:
        _log.exception("manual_payment_request")
        await callback.message.answer(_MSG_SERVER_UNAVAILABLE)
        return

    try:
        request_id = int(data["request_id"])
        created = bool(data["created"])
        sub_raw = data.get("subscriber_id")
        subscriber_id = int(sub_raw) if sub_raw is not None else None
    except (KeyError, TypeError, ValueError):
        _log.warning("manual_payment_request: неожиданное тело ответа API")
        await callback.message.answer(_MSG_SERVER_UNAVAILABLE)
        return

    if created:
        await callback.message.answer(
            "Заявка принята, ожидайте проверки администратором."
        )
        try:
            await notify_admins_manual_payment(
                callback.bot,
                settings,
                request_id=request_id,
                telegram_user_id=uid,
                subscriber_id=subscriber_id,
            )
        except Exception:
            _log.exception("notify_admins_manual_payment")
    else:
        await callback.message.answer("Заявка уже на рассмотрении.")


@router.message(Command("status"))
async def cmd_status(message: Message, api: InternalApiClient) -> None:
    if message.from_user is None:
        await message.answer("Нет данных пользователя.")
        return
    try:
        sid = await api.resolve_subscriber_by_telegram(message.from_user.id)
    except httpx.HTTPStatusError as exc:
        _log.warning("resolve_subscriber HTTP %s", exc.response.status_code)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except httpx.RequestError as exc:
        _log.warning("resolve_subscriber сеть: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except Exception as exc:
        _log.exception("resolve_subscriber: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    if sid is None:
        await message.answer(_MSG_NOT_LINKED)
        return
    try:
        data = await api.subscription_status(sid)
    except httpx.HTTPStatusError as exc:
        _log.warning("subscription_status HTTP %s", exc.response.status_code)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except httpx.RequestError as exc:
        _log.warning("subscription_status сеть: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except Exception as exc:
        _log.exception("subscription_status неожиданная ошибка: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    if not data.get("active"):
        await message.answer("Активной подписки нет. Обратитесь к администратору для выдачи доступа.")
        return
    await message.answer(f"Подписка активна до: {data.get('ends_at')}")


@router.message(Command("get_link"))
async def cmd_get_link(message: Message, api: InternalApiClient) -> None:
    if message.from_user is None:
        await message.answer("Нет данных пользователя.")
        return
    try:
        sid = await api.resolve_subscriber_by_telegram(message.from_user.id)
    except httpx.HTTPStatusError as exc:
        _log.warning("resolve_subscriber HTTP %s", exc.response.status_code)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except httpx.RequestError as exc:
        _log.warning("resolve_subscriber сеть: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except Exception as exc:
        _log.exception("resolve_subscriber: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    if sid is None:
        await message.answer(_MSG_NOT_LINKED)
        return
    try:
        data = await api.subscription_status(sid)
    except httpx.HTTPStatusError as exc:
        _log.warning("get_link status HTTP %s", exc.response.status_code)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except httpx.RequestError as exc:
        _log.warning("get_link status сеть: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    except Exception as exc:
        _log.exception("get_link status неожиданная ошибка: %s", exc)
        await message.answer(_MSG_SERVER_UNAVAILABLE)
        return
    if not data.get("active"):
        await message.answer(
            "Активной подписки нет. Бот не выдаёт доступ автоматически. "
            "Обратитесь к администратору (mc-cli grant-access)."
        )
        return
    try:
        url = await api.reissue_link(sid)
    except httpx.HTTPStatusError as exc:
        _log.warning("reissue HTTP %s", exc.response.status_code)
        await message.answer(_MSG_LINK_FAILED)
        return
    except httpx.RequestError as exc:
        _log.warning("reissue сеть: %s", exc)
        await message.answer(_MSG_LINK_FAILED)
        return
    except Exception as exc:
        _log.exception("reissue неожиданная ошибка: %s", exc)
        await message.answer(_MSG_LINK_FAILED)
        return
    await message.answer(f"Ссылка для входа (одноразовая):\n{url}")
