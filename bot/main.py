"""Точка входа бота: long polling, без webhook."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.client import InternalApiClient
from bot.config import BotSettings, get_bot_settings
from bot.handlers import router
from bot.middlewares import InjectMiddleware


def _exit_if_bot_env_incomplete(settings: BotSettings) -> None:
    """Без токена и ключа polling бессмысленен — выходим без pydantic-traceback."""
    missing: list[str] = []
    if not settings.bot_token.strip():
        missing.append("BOT_TOKEN")
    if not settings.internal_api_key.strip():
        missing.append("INTERNAL_API_KEY")
    if not missing:
        return
    print(
        "Для запуска бота задайте в .env переменные BOT_TOKEN и INTERNAL_API_KEY "
        "(непустые значения). Сейчас не задано: "
        + ", ".join(missing)
        + ".\n"
        "Поднять только сайт (app) можно без этих переменных — см. .env.example.",
        file=sys.stderr,
    )
    raise SystemExit(1)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_bot_settings()
    _exit_if_bot_env_incomplete(settings)
    api = InternalApiClient(settings.internal_api_base_url, settings.internal_api_key)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        dispatcher = Dispatcher()
        dispatcher.update.middleware(InjectMiddleware(settings, api))
        dispatcher.include_router(router)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await api.aclose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
