"""Точка входа бота: long polling, без webhook."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.client import InternalApiClient
from bot.config import get_bot_settings
from bot.handlers import router
from bot.middlewares import InjectMiddleware


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_bot_settings()
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
