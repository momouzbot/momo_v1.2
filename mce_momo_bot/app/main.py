"""
Core dispatcher — FastAPI ilovasi.

TZ 2.1-bo'lim:
    Telegram -> https://domain.uz/webhook/{bot_id} -> Dispatcher -> Modul

TZ 10-bo'lim, 1-qadam: "Core dispatcher — webhook qabul qilish,
bot_id bo'yicha yo'naltirish" — shu fayl aynan shu vazifani bajaradi.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from aiogram import Bot as AiogramBot
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request

from app.config import settings
from app.database import AsyncSessionLocal
from app.dispatcher.router import BotNotActiveError, BotNotFoundError, dispatch_update
from app.momo_bot import build_momo_dispatcher
from app.services.scheduler import shutdown_scheduler, start_scheduler
from app.api.registration import router as registration_router
from app.api.payments import router as payments_router
from app.api.admin import router as admin_router
from app.api.external_bots import router as external_bots_router

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

# Momo botining (asosiy boshqaruv boti) aiogram obyektlari — global,
# chunki bitta jarayonda faqat bitta Momo bot instansiyasi bo'ladi
# (client botlardan farqli, ular BotRegistry orqali dinamik yuklanadi).
momo_aiogram_bot: AiogramBot | None = None
momo_dispatcher = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global momo_aiogram_bot, momo_dispatcher

    start_scheduler()

    if settings.momo_bot_token:
        momo_aiogram_bot = AiogramBot(token=settings.momo_bot_token)
        momo_dispatcher = build_momo_dispatcher()
        try:
            webhook_url = settings.webhook_url_for("momo")
            await momo_aiogram_bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info("Momo bot webhooki o'rnatildi: %s", webhook_url)
        except Exception:
            logger.exception("Momo bot webhookini o'rnatishda xato")
    else:
        logger.warning("MOMO_BOT_TOKEN sozlanmagan — Momo bot faol emas.")

    logger.info("MCE Momo Bot dispatcher ishga tushdi (env=%s)", settings.app_env)
    yield

    if momo_aiogram_bot:
        await momo_aiogram_bot.session.close()
    shutdown_scheduler()


app = FastAPI(title="MCE Momo Bot — Multi-bot Webhook Dispatcher", lifespan=lifespan)
app.include_router(registration_router)
app.include_router(payments_router)
app.include_router(admin_router)
app.include_router(external_bots_router)


@app.get("/health")
async def health() -> dict:
    """Server ishlab turganini tekshirish uchun (load balancer/monitoring)."""
    return {"status": "ok"}


@app.post("/webhook/momo")
async def momo_webhook(request: Request) -> dict:
    """Momo botining o'zi uchun alohida webhook — mijoz bilan to'g'ridan-to'g'ri suhbat (TZ 5-bo'lim)."""
    if momo_aiogram_bot is None or momo_dispatcher is None:
        logger.warning("Momo bot update qabul qildi, lekin sozlanmagan (MOMO_BOT_TOKEN yo'q).")
        return {"ok": True}

    update_data = await request.json()
    update = Update.model_validate(update_data)

    try:
        await momo_dispatcher.feed_update(momo_aiogram_bot, update)
    except Exception:
        logger.exception("Momo bot update qayta ishlashda xatolik")

    return {"ok": True}


@app.post("/webhook/{bot_id}")
async def telegram_webhook(bot_id: int, request: Request) -> dict:
    """
    Barcha mijoz botlarining Telegram update'lari shu yagona endpoint orqali keladi.
    bot_id — Telegram tomonidan berilgan bot identifikatori (webhook path'ida).
    """
    update_data = await request.json()

    async with AsyncSessionLocal() as session:
        try:
            await dispatch_update(session, bot_id, update_data)
        except BotNotFoundError:
            # Telegram webhook javobni 200 kutadi — 404 qaytarish qayta-qayta
            # urinishlarga sabab bo'lishi mumkin, shu sababli log + 200 qaytariladi.
            logger.warning("Noma'lum bot_id uchun update keldi: %s", bot_id)
        except BotNotActiveError as exc:
            logger.info("Faol bo'lmagan bot uchun update keldi: %s (%s)", bot_id, exc)

    # Telegramga har doim 200 qaytariladi — aks holda webhook qayta yuborishga urinadi.
    return {"ok": True}
