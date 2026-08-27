"""
Tashqi hostingdagi botlar uchun trafik hisobot va holat tekshirish API'si.

Ssenariy: GOT Game (yoki shunga o'xshash platforma) o'z serverida mijozlarga
alohida mini-botlar yasab beradi (har bir mijoz — alohida Telegram bot).
Momo bu mini-botlarni HOSTINGLAMAYDI, lekin har birining tarif rejasini va
trafigini alohida-alohida (bot_id bo'yicha) nazorat qiladi:

    1. Har bir mini-bot GOT Game tomonidan yaratilganda, GOT Game serveri
       Momo'ning `/api/registration/register` endpointiga shu mijozning
       (owner_telegram_id) nomidan `externally_hosted=true` bilan murojaat
       qiladi va noyob `external_api_key` oladi.
    2. GOT Game serveri davriy ravishda (masalan har kuni) shu kalit orqali
       `/report-usage` chaqirib, mini-botning noyob foydalanuvchilar sonini
       yuboradi — Momo shu asosda hosting narxini hisoblaydi (TZ 6.3).
    3. GOT Game serveri istalgan vaqtda `/status` orqali Momo'dan mini-bot
       holatini so'rashi mumkin: agar Momo uni PAUSED (hosting to'lanmagan)
       yoki SUSPENDED (tarif muddati tugagan) deb belgilagan bo'lsa, GOT Game
       o'z tomonida shu mini-botga xizmat ko'rsatishni to'xtatishi kerak —
       Momo botni bevosita boshqarmaydi, faqat ruxsat/holat signalini beradi.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.base import BotStatus
from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff

router = APIRouter(prefix="/api/external-bots", tags=["external-bots"])


async def _authorize_bot(session, bot_id: int, api_key: str) -> BotModel:
    result = await session.execute(select(BotModel).where(BotModel.id == bot_id))
    bot_row = result.scalar_one_or_none()

    if bot_row is None:
        raise HTTPException(status_code=404, detail="Bot topilmadi.")
    if not bot_row.is_externally_hosted:
        raise HTTPException(status_code=400, detail="Bu bot tashqi hostingda ro'yxatdan o'tmagan.")
    if not bot_row.external_api_key or bot_row.external_api_key != api_key:
        raise HTTPException(status_code=403, detail="Noto'g'ri api_key.")

    return bot_row


class ReportUsageRequest(BaseModel):
    api_key: str = Field(..., description="Ro'yxatdan o'tishda berilgan external_api_key")
    unique_user_count: int = Field(..., ge=0, description="Joriy noyob foydalanuvchilar soni")


class ReportUsageResponse(BaseModel):
    bot_id: int
    unique_user_count: int
    estimated_hosting_price: float
    bot_status: BotStatus
    should_serve: bool = Field(
        description="False bo'lsa — GOT Game shu mini-botga xizmat ko'rsatishni to'xtatishi kerak"
    )


class BotStatusResponse(BaseModel):
    bot_id: int
    bot_status: BotStatus
    tariff_code: str | None
    tariff_expires_at: str | None
    should_serve: bool


@router.post("/{bot_id}/report-usage", response_model=ReportUsageResponse)
async def report_usage(bot_id: int, payload: ReportUsageRequest) -> ReportUsageResponse:
    async with AsyncSessionLocal() as session:
        bot_row = await _authorize_bot(session, bot_id, payload.api_key)

        bot_row.external_user_count = payload.unique_user_count
        await session.commit()

        from app.services.limits import calculate_hosting_price

        price = await calculate_hosting_price(session, bot_id, payload.unique_user_count)

        return ReportUsageResponse(
            bot_id=bot_id,
            unique_user_count=payload.unique_user_count,
            estimated_hosting_price=price,
            bot_status=bot_row.status,
            should_serve=bot_row.status == BotStatus.ACTIVE,
        )


@router.get("/{bot_id}/status", response_model=BotStatusResponse)
async def get_bot_status(bot_id: int, api_key: str = Query(...)) -> BotStatusResponse:
    """
    GOT Game (yoki boshqa tashqi platforma) davriy ravishda shu endpoint
    orqali mini-bot xizmat ko'rsatishda davom etishi kerakmi-yo'qmi
    tekshirishi mumkin — masalan hosting to'lanmasa yoki tarif muddati
    tugasa, Momo statusni PAUSED/SUSPENDED qilib qo'yadi va `should_serve`
    false bo'lib qaytadi.
    """
    async with AsyncSessionLocal() as session:
        bot_row = await _authorize_bot(session, bot_id, api_key)

        tariff_result = await session.execute(
            select(BotTariff).where(BotTariff.bot_id == bot_id, BotTariff.is_active.is_(True))
        )
        active_tariff = tariff_result.scalar_one_or_none()

        return BotStatusResponse(
            bot_id=bot_id,
            bot_status=bot_row.status,
            tariff_code=active_tariff.tariff_code.value if active_tariff else None,
            tariff_expires_at=(
                active_tariff.expires_at.isoformat() if active_tariff and active_tariff.expires_at else None
            ),
            should_serve=bot_row.status == BotStatus.ACTIVE,
        )

