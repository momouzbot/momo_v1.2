"""
Core dispatcher: Telegram → /webhook/{bot_id} → tegishli modul handleriga yo'naltirish.

TZ 2.1-bo'lim arxitekturasi shu yerda amalga oshadi.
"""
from __future__ import annotations

import logging

from aiogram import Bot as AiogramBot
from aiogram.types import Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatcher.registry import bot_registry
from app.models.base import BotStatus, ModuleType
from app.models.bot import Bot as BotModel
from app.services.crypto import decrypt_token
from app.services.modules import DEVELOPMENT_NOTICE, is_module_active

logger = logging.getLogger(__name__)


class BotNotFoundError(Exception):
    pass


class BotNotActiveError(Exception):
    pass


async def resolve_bot(session: AsyncSession, telegram_bot_id: int) -> BotModel:
    """bot_id bo'yicha DB'dan bot yozuvini topadi va holatini tekshiradi."""
    result = await session.execute(select(BotModel).where(BotModel.telegram_bot_id == telegram_bot_id))
    bot_row = result.scalar_one_or_none()

    if bot_row is None:
        raise BotNotFoundError(f"Bot topilmadi: {telegram_bot_id}")

    if bot_row.status != BotStatus.ACTIVE:
        # PAUSED (hosting to'lanmagan) yoki SUSPENDED (tarif tugagan) — TZ 6.4, 6.5
        raise BotNotActiveError(f"Bot faol emas: {telegram_bot_id} (status={bot_row.status})")

    return bot_row


async def _send_development_notice(bot_row: BotModel, update: Update) -> None:
    """
    Modul admin panelda o'chirilgan yoki hali tayyor bo'lmagan bo'lsa,
    foydalanuvchiga xabar beriladi. Faqat oddiy matnli xabarlarga javob
    beriladi (callback/boshqa hodisalar uchun spam qilinmaydi).
    """
    if update.message is None:
        return

    token = decrypt_token(bot_row.token_encrypted)
    aiogram_bot = AiogramBot(token=token)
    try:
        await aiogram_bot.send_message(chat_id=update.message.chat.id, text=DEVELOPMENT_NOTICE)
    except Exception:
        logger.warning("Development notice yuborilmadi: bot_id=%s", bot_row.telegram_bot_id)
    finally:
        await aiogram_bot.session.close()


async def dispatch_update(session: AsyncSession, telegram_bot_id: int, update_data: dict) -> None:
    """
    Kelgan Telegram update'ni tegishli bot instansiyasiga yetkazadi.
    Bot birinchi marta chaqirilsa — lazy-load qilinadi.

    Modul admin panelda o'chirilgan bo'lsa (Module.is_active=False) — update
    modul handlerlariga yuborilmaydi, o'rniga "xizmat ishlab chiqilmoqda"
    xabari qaytariladi. Shu tekshiruv har bir update'da amalga oshadi, shu
    sababli admin panel orqali o'zgartirish darhol kuchga kiradi (keshlanmaydi).
    """
    bot_row = await resolve_bot(session, telegram_bot_id)

    if bot_row.is_externally_hosted:
        # Bu bot boshqa serverda ishlaydi — Momo webhook o'rnatmagan, shu
        # sababli bu yerga update kelishi kutilmagan holat (masalan eski
        # webhook konfiguratsiyasi qolib ketgan bo'lishi mumkin). Xavfsizlik
        # uchun e'tiborsiz qoldiriladi, modul handlerlariga yuborilmaydi.
        logger.warning(
            "Tashqi hostingdagi bot uchun kutilmagan update keldi: bot_id=%s", telegram_bot_id
        )
        return

    module_active = await is_module_active(session, ModuleType(bot_row.module_type))
    update = Update.model_validate(update_data)

    if not module_active:
        bot_registry.unload(telegram_bot_id)  # kesh xotirasini bo'shatish
        await _send_development_notice(bot_row, update)
        return

    instance = bot_registry.get(telegram_bot_id)
    if instance is None:
        token = decrypt_token(bot_row.token_encrypted)
        instance = await bot_registry.load(bot_row, token)

    try:
        await instance.dispatcher.feed_update(instance.aiogram_bot, update)
    except Exception:
        # TZ 11-bo'lim: "har bir modul handlerida try/except" — xatolik izolyatsiyasi.
        # Bitta botdagi xatolik boshqa botlarga yoki dispatcherga ta'sir qilmasligi kerak.
        logger.exception("Update qayta ishlashda xatolik: bot_id=%s", telegram_bot_id)
