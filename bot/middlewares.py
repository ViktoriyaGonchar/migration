"""Проброс BotSettings и InternalApiClient в хендлеры (единственный способ DI в этом MVP)."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.client import InternalApiClient
from bot.config import BotSettings


class InjectMiddleware(BaseMiddleware):
    def __init__(self, settings: BotSettings, api: InternalApiClient) -> None:
        self._settings = settings
        self._api = api

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["settings"] = self._settings
        data["api"] = self._api
        return await handler(event, data)
