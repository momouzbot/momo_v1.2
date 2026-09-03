"""
Boshlang'ich ma'lumotlarni yuklash: tariffs (TZ 6.1-jadval) va modules (TZ 3.3-jadval).
Ishlatish: python -m app.seed
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.base import ModuleType, TariffCode
from app.models.module import Module
from app.models.tariff import Tariff

TARIFFS = [
    dict(
        code=TariffCode.START,
        name="Start",
        bot_limit=1,
        edit_limit_per_day=2,
        upgrade_price=0,
        base_hosting_price=5000,
        user_threshold=1000,
        duration_days=None,  # muddatsiz
    ),
    dict(
        code=TariffCode.STANDARD,
        name="Standard",
        bot_limit=2,
        edit_limit_per_day=4,
        upgrade_price=0,  # admin belgilaydi — boshlang'ich qiymat 0, keyin admin panelda o'rnatiladi
        base_hosting_price=3000,
        user_threshold=1000,
        duration_days=180,
    ),
    dict(
        code=TariffCode.PREMIUM,
        name="Premium",
        bot_limit=7,
        edit_limit_per_day=10,
        upgrade_price=0,
        base_hosting_price=1500,
        user_threshold=1000,
        duration_days=180,
    ),
]

MODULES = [
    (ModuleType.ADMIN, "Admin-bot", "Kanal/guruh boshqaruvi: avto-post, statistika, spam filtri", False),
    (ModuleType.SUPPORT, "Murojaat-bot", "Foydalanuvchi murojaatlari va admin javoblari", True),
    (ModuleType.KINO, "Kino-bot", "Kod/nom bo'yicha kino qidiruv va statistikasi", True),
    (ModuleType.SHOP, "Shop-bot", "Katalog, savat va buyurtma tizimi", False),
    (ModuleType.GAME_GOT, "O'yin-bot: GOT Game", "Resurs boshqaruvi va urush mexanikasi", True),
    (ModuleType.GAME_MAFIA, "O'yin-bot: Mafia", "Qisqa sessiyali rol-ovoz berish o'yini", False),
    (ModuleType.GAME_BUNKER, "O'yin-bot: Bunker", "Raund-based muhokama va ovoz berish o'yini", False),
    (ModuleType.CUSTOM, "Custom-bot", "Konstruktor: buyruq/javob va tugmali menyu", False),
]


async def seed() -> None:
    print("[SEED-DEBUG] Boshlandi. Session ochilmoqda...", flush=True)
    async with AsyncSessionLocal() as session:
        print("[SEED-DEBUG] Session ochildi. Tariffs tekshirilmoqda...", flush=True)
        for data in TARIFFS:
            existing = await session.execute(select(Tariff).where(Tariff.code == data["code"]))
            if existing.scalar_one_or_none() is None:
                session.add(Tariff(**data))

        print("[SEED-DEBUG] Tariffs tayyor. Modules tekshirilmoqda...", flush=True)
        for code, name, description, is_active in MODULES:
            existing = await session.execute(select(Module).where(Module.code == code))
            if existing.scalar_one_or_none() is None:
                session.add(Module(code=code, name=name, description=description, is_active=is_active))

        print("[SEED-DEBUG] Commit qilinmoqda...", flush=True)
        await session.commit()
    print("[SEED-DEBUG] Session yopildi. Seed muvaffaqiyatli yakunlandi: tariffs + modules.", flush=True)


if __name__ == "__main__":
    print("[SEED-DEBUG] python -m app.seed ishga tushdi.", flush=True)
    try:
        asyncio.run(asyncio.wait_for(seed(), timeout=30))
    except TimeoutError:
        print("[SEED-DEBUG] XATO: 30 soniyada tugamadi — TIMEOUT!", flush=True)
        raise
    except Exception as exc:
        print(f"[SEED-DEBUG] XATO: {type(exc).__name__}: {exc}", flush=True)
        raise
    print("[SEED-DEBUG] Skript to'liq tugadi, chiqilmoqda.", flush=True)
