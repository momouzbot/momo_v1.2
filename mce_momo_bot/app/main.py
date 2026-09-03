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

from fastapi import FastAPI, HTTPException, Request

from app.config import settings
from app.database import AsyncSessionLocal
from app.dispatcher.router import BotNotActiveError, BotNotFoundError, dispatch_update
from app.services.scheduler import shutdown_scheduler, start_scheduler
from app.api.registration import router as registration_router
from app.api.payments import router as payments_router
from app.api.admin import router as admin_router
from app.api.external_bots import router as external_bots_router

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

print("[MAIN-DEBUG] app/main.py fayli import qilindi.", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[MAIN-DEBUG] Lifespan boshlandi. Scheduler ishga tushirilmoqda...", flush=True)
    start_scheduler()
    print("[MAIN-DEBUG] Scheduler ishga tushdi. Ilova tayyor.", flush=True)
    logger.info("MCE Momo Bot dispatcher ishga tushdi (env=%s)", settings.app_env)
    yield
    shutdown_scheduler()


print("[MAIN-DEBUG] FastAPI ilova obyekti yaratilmoqda...", flush=True)
app = FastAPI(title="MCE Momo Bot — Multi-bot Webhook Dispatcher", lifespan=lifespan)
app.include_router(registration_router)
app.include_router(payments_router)
app.include_router(admin_router)
app.include_router(external_bots_router)


@app.get("/health")
async def health() -> dict:
    """Server ishlab turganini tekshirish uchun (load balancer/monitoring)."""
    return {"status": "ok"}


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
