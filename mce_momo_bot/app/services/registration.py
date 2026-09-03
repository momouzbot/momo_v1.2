"""
Ro'yxatdan o'tish (registration) HTTP API — TZ 5-bo'lim.

Asosiy biznes logika `app/services/registration.py` da; bu yerda faqat
HTTP darajasidagi xato-kodlarga o'tkazish bor. Asosiy foydalanuvchi
tajribasi — Momo bot suhbat oqimi (`app/momo_bot.py`); bu API tashqi
integratsiyalar (masalan admin panel, boshqa xizmatlar) uchun.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas import RegisterBotRequest, RegisterBotResponse
from app.database import AsyncSessionLocal
from app.models.base import TariffCode
from app.services.limits import LimitExceededError
from app.services.registration import AlreadyRegisteredError, register_bot_for_owner
from app.services.telegram import InvalidTokenError

router = APIRouter(prefix="/api/registration", tags=["registration"])


@router.post("/register", response_model=RegisterBotResponse)
async def register_bot(payload: RegisterBotRequest) -> RegisterBotResponse:
    async with AsyncSessionLocal() as session:
        try:
            bot_row, external_api_key = await register_bot_for_owner(
                session,
                owner_telegram_id=payload.owner_telegram_id,
                owner_username=payload.owner_username,
                owner_full_name=payload.owner_full_name,
                bot_token=payload.bot_token,
                module_type=payload.module_type,
                externally_hosted=payload.externally_hosted,
            )
        except InvalidTokenError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AlreadyRegisteredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except LimitExceededError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

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
