"""
DBSessionMiddleware — har bir kelgan update uchun alohida AsyncSession
ochadi va handler ichida `session` argumenti sifatida uzatadi.

Aiogram 3 outer middleware sifatida ro'yxatdan o'tkaziladi, shunda u
barcha handler turlari (message, callback_query va h.k.) uchun ishlaydi.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.database import AsyncSessionLocal


class DBSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with AsyncSessionLocal() as session:
            data["session"] = session
            return await handler(event, data)
