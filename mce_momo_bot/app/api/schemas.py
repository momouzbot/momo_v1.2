"""
Ro'yxatdan o'tish (registration) API uchun Pydantic sxemalari.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field

from app.models.base import BotStatus, ModuleType, TariffCode


class RegisterBotRequest(BaseModel):
    """Mijoz yangi bot qo'shmoqchi bo'lganda yuboradigan ma'lumot."""

    owner_telegram_id: int = Field(..., description="Mijozning shaxsiy Telegram ID raqami")
    owner_username: str | None = None
    owner_full_name: str | None = None

    bot_token: str = Field(..., min_length=20, description="BotFather'dan olingan token")
    module_type: ModuleType = Field(..., description="Bot turi: admin, support, kino, shop, game_*, custom")

    externally_hosted: bool = Field(
        default=False,
        description=(
            "True bo'lsa, bot boshqa serverda ishlaydi (masalan GOT Game). "
            "Momo webhook o'rnatmaydi, faqat tarif/trafik nazoratini oladi."
        ),
    )


class RegisterBotResponse(BaseModel):
    bot_id: int
    telegram_bot_id: int
    username: str
    module_type: ModuleType
    status: BotStatus
    tariff_code: TariffCode
    tariff_expires_at: datetime.date | None
    webhook_set: bool
    is_externally_hosted: bool = False
    external_api_key: str | None = Field(
        default=None,
        description="Faqat externally_hosted=true bo'lganda qaytariladi — trafik hisoboti uchun saqlab qo'ying.",
    )


class ErrorResponse(BaseModel):
    detail: str
