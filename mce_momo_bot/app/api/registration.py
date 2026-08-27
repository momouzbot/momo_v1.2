"""
Ro'yxatdan o'tish (registration) oqimi — TZ 5-bo'lim.

Qadamlar:
    1. Bot token Telegram getMe orqali tekshiriladi (noto'g'ri bo'lsa aniq xato)
    2. Mijoz (User) topiladi yoki yaratiladi
    3. Yangi bot har doim "Start" tarifida ro'yxatdan o'tadi (TZ 6.1) —
       tarifni oshirish alohida oqim orqali amalga oshadi (to'lov + admin tasdig'i)
    4. Bot limiti tekshiriladi (Start tarifi bot_limit=1)
    5. Bot yozuvi yaratiladi, token shifrlanadi
    6. Webhook o'rnatiladi — FAQAT Momo o'zi hostinglaydigan botlar uchun.
       `externally_hosted=true` bo'lsa (masalan GOT Game — alohida serverda
       ishlaydi), webhook o'rnatilmaydi; o'rniga tarif/trafik nazorati uchun
       maxfiy kalit (`external_api_key`) generatsiya qilinadi va bir marta
       javobda qaytariladi (TZ'dan tashqari, mijozning so'rovi bo'yicha).
    7. Xatolik yuz bersa — yaratilgan yozuvlar bekor qilinadi (rollback)
"""
from __future__ import annotations

import datetime
import logging
import secrets

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.base import BotStatus, TariffCode
from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff
from app.services.crypto import encrypt_token
from app.services.limits import LimitExceededError, check_bot_limit, get_tariff_by_code
from app.services.telegram import InvalidTokenError, set_webhook, validate_token
from app.services.users import get_or_create_user

from app.api.schemas import RegisterBotRequest, RegisterBotResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/registration", tags=["registration"])


@router.post("/register", response_model=RegisterBotResponse)
async def register_bot(payload: RegisterBotRequest) -> RegisterBotResponse:
    async with AsyncSessionLocal() as session:
        # --- 1. Token validatsiyasi ---
        try:
            me = await validate_token(payload.bot_token)
        except InvalidTokenError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # --- Bot allaqachon ro'yxatdan o'tganmi? ---
        existing = await session.execute(
            select(BotModel).where(BotModel.telegram_bot_id == me.bot_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409, detail="Bu bot allaqachon ro'yxatdan o'tgan."
            )

        # --- 2. Mijozni topish/yaratish ---
        user = await get_or_create_user(
            session,
            telegram_id=payload.owner_telegram_id,
            username=payload.owner_username,
            full_name=payload.owner_full_name,
        )

        # --- 3-4. Start tarifi va bot limiti tekshiruvi ---
        start_tariff = await get_tariff_by_code(session, TariffCode.START)
        try:
            await check_bot_limit(session, owner_id=user.id, tariff=start_tariff)
        except LimitExceededError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        # --- 5. Bot yozuvini yaratish ---
        external_api_key = secrets.token_urlsafe(32) if payload.externally_hosted else None

        bot_row = BotModel(
            owner_id=user.id,
            telegram_bot_id=me.bot_id,
            username=me.username,
            token_encrypted=encrypt_token(payload.bot_token),
            module_type=payload.module_type,
            status=BotStatus.ACTIVE,
            webhook_set=False,
            is_externally_hosted=payload.externally_hosted,
            external_api_key=external_api_key,
        )
        session.add(bot_row)
        await session.flush()  # bot_row.id kerak bo'ladi

        session.add(
            BotTariff(
                bot_id=bot_row.id,
                tariff_code=TariffCode.START,
                started_at=datetime.date.today(),
                expires_at=None,  # Start — muddatsiz (TZ 6.1)
                is_active=True,
            )
        )

        # --- 6. Webhook o'rnatish (faqat Momo hostinglaydigan botlar uchun) ---
        if not payload.externally_hosted:
            try:
                await set_webhook(payload.bot_token, me.bot_id)
                bot_row.webhook_set = True
            except Exception as exc:
                # Webhook o'rnatilmasa ham bot yozuvi qoladi — keyinroq qayta urinish mumkin
                # (masalan alohida retry endpoint yoki background job orqali).
                logger.warning("Webhook o'rnatilmadi: bot_id=%s xato=%s", me.bot_id, exc)
        else:
            logger.info(
                "Tashqi hostingdagi bot ro'yxatdan o'tdi (webhook o'rnatilmaydi): bot_id=%s",
                me.bot_id,
            )

        await session.commit()
        await session.refresh(bot_row)

        return RegisterBotResponse(
            bot_id=bot_row.id,
            telegram_bot_id=bot_row.telegram_bot_id,
            username=bot_row.username,
            module_type=bot_row.module_type,
            status=bot_row.status,
            tariff_code=TariffCode.START,
            tariff_expires_at=None,
            webhook_set=bot_row.webhook_set,
            is_externally_hosted=bot_row.is_externally_hosted,
            external_api_key=external_api_key,
        )

