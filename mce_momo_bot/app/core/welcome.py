"""
Xush kelibsiz xabari — TZ 3.2-bo'lim.
Yangi a'zo guruhga qo'shilganda bot_row.welcome_message matnini yuboradi.

Eslatma: hozircha faqat matn qo'llab-quvvatlanadi (bots.welcome_message —
String ustuni). Rasm/video bilan xush kelibsiz kerak bo'lsa, keyinchalik
welcome_media_file_id va welcome_media_type ustunlari qo'shiladi.
"""
from __future__ import annotations

from aiogram import Dispatcher, F
from aiogram.types import Message

from app.models.bot import Bot as BotModel


def register_welcome(dp: Dispatcher, bot_row: BotModel) -> None:
    @dp.message(F.new_chat_members)
    async def send_welcome(message: Message) -> None:
        if not bot_row.welcome_message:
            return
        for member in message.new_chat_members:
            if member.is_bot:
                continue
            text = bot_row.welcome_message.replace("{name}", member.full_name)
            await message.answer(text)
