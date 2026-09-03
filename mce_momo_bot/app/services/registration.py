"""
Bot ro'yxatdan o'tkazish — qayta ishlatiladigan biznes logika.

Bu funksiya ikki joyda ishlatiladi:
    1. HTTP API (`app/api/registration.py`) — tashqi integratsiyalar uchun
    2. Momo bot suhbat oqimi (`app/momo_bot.py`) — mijoz Telegram orqali
       to'g'ridan-to'g'ri shu yerda o'zining botini ro'yxatdan o'tkazadi
       (TZ 5-bo'lim: asosiy, kutilgan foydalanuvchi tajribasi)
"""
from __future__ import annotations

import datetime
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BotStatus, ModuleType, TariffCode
from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff
from app.services.crypto import encrypt_token
from app.services.limits import LimitExceededError, check_bot_limit, get_tariff_by_code
from app.services.telegram import InvalidTokenError, set_webhook, validate_token
from app.services.users import get_or_create_user

logger = logging.getLogger(__name__)


class AlreadyRegisteredError(Exception):
    """Bu bot allaqachon ro'yxatdan o'tgan."""


async def register_bot_for_owner(
    session: AsyncSession,
    *,
    owner_telegram_id: int,
    owner_username: str | None,
    owner_full_name: str | None,
    bot_token: str,
    module_type: ModuleType,
    externally_hosted: bool = False,
) -> tuple[BotModel, str | None]:
    """
    To'liq ro'yxatdan o'tkazish oqimi (TZ 5-bo'lim).

    Qaytaradi: (bot_row, external_api_key). external_api_key faqat
    externally_hosted=True bo'lganda qiymatga ega, aks holda None.

    Xatoliklar:
        InvalidTokenError    — token noto'g'ri
        AlreadyRegisteredError — bot allaqachon ro'yxatdan o'tgan
        LimitExceededError   — bot limiti tugagan
    """
    # --- 1. Token validatsiyasi ---
    me = await validate_token(bot_token)  # InvalidTokenError ko'tarilishi mumkin

    # --- Bot allaqachon ro'yxatdan o'tganmi? ---
    existing = await session.execute(select(BotModel).where(BotModel.telegram_bot_id == me.bot_id))
    if existing.scalar_one_or_none() is not None:
        raise AlreadyRegisteredError(f"Bu bot allaqachon ro'yxatdan o'tgan: {me.username}")

    # --- 2. Mijozni topish/yaratish ---
    user = await get_or_create_user(
        session, telegram_id=owner_telegram_id, username=owner_username, full_name=owner_full_name
    )

    # --- 3-4. Start tarifi va bot limiti tekshiruvi ---
    start_tariff = await get_tariff_by_code(session, TariffCode.START)
    await check_bot_limit(session, owner_id=user.id, tariff=start_tariff)  # LimitExceededError

    # --- 5. Bot yozuvini yaratish ---
    external_api_key = secrets.token_urlsafe(32) if externally_hosted else None

    bot_row = BotModel(
        owner_id=user.id,
        telegram_bot_id=me.bot_id,
        username=me.username,
        token_encrypted=encrypt_token(bot_token),
        module_type=module_type,
        status=BotStatus.ACTIVE,
        webhook_set=False,
        is_externally_hosted=externally_hosted,
        external_api_key=external_api_key,
    )
    session.add(bot_row)
    await session.flush()

    session.add(
        BotTariff(
            bot_id=bot_row.id,
            tariff_code=TariffCode.START,
            started_at=datetime.date.today(),
            expires_at=None,
            is_active=True,
        )
    )

    # --- 6. Webhook o'rnatish (faqat Momo hostinglaydigan botlar uchun) ---
    if not externally_hosted:
        try:
            await set_webhook(bot_token, me.bot_id)
            bot_row.webhook_set = True
        except Exception as exc:
            logger.warning("Webhook o'rnatilmadi: bot_id=%s xato=%s", me.bot_id, exc)
    else:
        logger.info("Tashqi hostingdagi bot ro'yxatdan o'tdi: bot_id=%s", me.bot_id)

    await session.commit()
    await session.refresh(bot_row)

    return bot_row, external_api_key
