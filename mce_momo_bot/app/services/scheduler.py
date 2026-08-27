"""
Markaziy scheduler — barcha botlar uchun bitta xizmat (TZ 2.1-bo'lim).
Vaqt asosidagi voqealar: AdminModule avto-post, GameModule kunlik hodisalar
(masalan GOT Game'da kunlik resurs yig'ish, TZ 4.5.1), hosting/tarif nazorati.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)


def start_scheduler() -> None:
    if not scheduler.running:
        _register_daily_jobs()
        scheduler.start()
        logger.info("Markaziy scheduler ishga tushdi (timezone=%s)", settings.scheduler_timezone)


def _register_daily_jobs() -> None:
    """TZ 6.4/6.5-bo'lim: har kuni 00:05 (Toshkent) da tarif/hosting nazorati."""
    from app.services.hosting_check import check_hosting_payments
    from app.services.tariff_check import check_tariff_expirations

    scheduler.add_job(
        check_tariff_expirations,
        trigger=CronTrigger(hour=0, minute=5),
        id="check_tariff_expirations",
        replace_existing=True,
    )
    scheduler.add_job(
        check_hosting_payments,
        trigger=CronTrigger(hour=0, minute=10),
        id="check_hosting_payments",
        replace_existing=True,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Markaziy scheduler to'xtatildi")


# TODO: TZ 11-bo'limdagi xavfga ko'ra, bot soni ko'paygach bu xizmatni
# alohida worker processga (masalan Celery beat) ajratish rejalashtiriladi.

