"""
Mijoz botlarida kutilmagan xatolik yuz berganda bot egasiga va Momo
Adminlarga avtomatik xabar yuborish.

MUHIM: bu — bot o'zining tarifi tugashi yoki hosting to'lanmagani kabi
KUTILGAN holatlar EMAS (ular allaqachon BotNotFoundError/BotNotActiveError
orqali alohida, jimgina qayta ishlanadi — TZ). Bu yerdagi xabarnoma faqat
KUTILMAGAN dasturiy xatolar uchun (masalan yetishmayotgan fayl, kod xatosi,
bazaga ulanish muammosi) — bunday hodisa avval faqat Railway logida
"sukut" bo'lib qolib ketardi, hech kimga bildirilmasdi.

Xabar aynan MOMO BOT orqali yuboriladi (mijoz botining o'zi emas) — chunki
aynan mijoz botining o'zi ishlamay qolgan bo'lishi mumkin (masalan uning
dispatcherini yuklab bo'lmayapti), Momo bot esa alohida, mustaqil ishlaydi.
"""
from __future__ import annotations

import datetime
import logging
import traceback

from aiogram import Bot as AiogramBot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot as BotModel
from app.models.user import User

logger = logging.getLogger(__name__)

# Bir xil bot uchun juda tez-tez (masalan har xabarda) qayta-qayta
# xabar yubormaslik uchun oddiy xotiradagi "cooldown". Server qayta ishga
# tushsa hisoblagich ham reset bo'ladi — bu muhim emas, faqat spam'ning
# oldini olish uchun ishlatiladi, aniq hisobot uchun emas.
_NOTIFY_COOLDOWN = datetime.timedelta(minutes=15)
_last_notified: dict[int, datetime.datetime] = {}


async def report_bot_error(
    session: AsyncSession, momo_bot: AiogramBot, telegram_bot_id: int, exc: Exception
) -> None:
    """
    telegram_bot_id — Telegram tomonidan berilgan bot ID (webhook yo'lidagi
    bot_id bilan bir xil, ya'ni bots.telegram_bot_id).
    """
    now = datetime.datetime.utcnow()
    last = _last_notified.get(telegram_bot_id)
    if last is not None and now - last < _NOTIFY_COOLDOWN:
        return  # shu bot uchun yaqinda xabar berilgan — spam bo'lmasin
    _last_notified[telegram_bot_id] = now

    logger.exception("Mijoz botida kutilmagan xatolik: telegram_bot_id=%s", telegram_bot_id)

    result = await session.execute(select(BotModel).where(BotModel.telegram_bot_id == telegram_bot_id))
    bot_row = result.scalar_one_or_none()

    # --- Bot egasiga (mijozga) — oddiy, qo'rqitmaydigan xabar ---
    if bot_row is not None:
        owner_result = await session.execute(select(User.telegram_id).where(User.id == bot_row.owner_id))
        owner_telegram_id = owner_result.scalar_one_or_none()
        if owner_telegram_id is not None:
            try:
                await momo_bot.send_message(
                    owner_telegram_id,
                    f"⚠️ @{bot_row.username} botingizda texnik nosozlik yuz berdi.\n\n"
                    "Bu haqda texnik jamoa allaqachon avtomatik xabardor qilindi va "
                    "tez orada hal qilinadi. Tushunganingiz uchun rahmat.",
                )
            except Exception:
                logger.exception("Bot egasiga xato haqida xabar yuborishda muammo")

    # --- Momo Adminlarga — texnik tafsilotlar bilan ---
    admins_result = await session.execute(select(User).where(User.is_momo_admin.is_(True)))
    admins = admins_result.scalars().all()
    if not admins:
        return

    bot_label = f"@{bot_row.username} (id={telegram_bot_id})" if bot_row else f"noma'lum bot (id={telegram_bot_id})"
    tb_tail = "\n".join(traceback.format_exc().strip().splitlines()[-4:])
    admin_text = (
        "🔴 Bot xatoligi (avtomatik aniqlandi)\n\n"
        f"Bot: {bot_label}\n"
        f"Xato turi: {type(exc).__name__}\n"
        f"Xabar: {exc}\n\n"
        f"...\n{tb_tail}\n\n"
        "To'liq traceback uchun Railway loglariga qarang."
    )
    for admin in admins:
        try:
            await momo_bot.send_message(admin.telegram_id, admin_text)
        except Exception:
            logger.exception("Adminga xato haqida xabar yuborishda muammo: admin_telegram_id=%s", admin.telegram_id)
