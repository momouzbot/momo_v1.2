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
        description=(
            "Bepul tarif — 1 ta bot, kuniga 3 tagacha tahrir. "
            "Botingizni sinab ko'rish va boshlash uchun ideal."
        ),
        bot_limit=1,
        edit_limit_per_day=3,
        upgrade_price=0,
        base_hosting_price=12000,
        weekly_hosting_price=3900,
        user_threshold=1000,
        duration_days=None,  # muddatsiz
        grace_period_days=0,
    ),
    dict(
        code=TariffCode.STANDARD,
        name="Standard",
        description=(
            "3 tagacha bot, kuniga 5 tahrir, 2 oy (60 kun) muddat. "
            "Muddat tugasa — ortiqcha botlar darhol to'xtatiladi."
        ),
        bot_limit=3,
        edit_limit_per_day=5,
        upgrade_price=49000,
        base_hosting_price=10000,
        weekly_hosting_price=2900,
        user_threshold=1000,
        duration_days=60,
        grace_period_days=0,
    ),
    dict(
        code=TariffCode.PREMIUM,
        name="Premium",
        description=(
            "5 tagacha bot, kuniga 10 tahrir, 6 oy (180 kun) muddat. "
            "Muddat tugasa ham botlar yana 30 kun faol qoladi (imtiyoz)."
        ),
        bot_limit=5,
        edit_limit_per_day=10,
        upgrade_price=150000,
        base_hosting_price=7000,
        weekly_hosting_price=1900,
        user_threshold=1000,
        duration_days=180,
        grace_period_days=30,
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
            tariff = existing.scalar_one_or_none()
            if tariff is None:
                session.add(Tariff(**data))
            else:
                # MUHIM O'ZGARISH: avval bu yerda bot_limit/edit_limit/narx/muddat
                # HAR DEPLOYDA kod ichidagi TARIFFS bilan qayta yozib qo'yilardi —
                # bu admin panel orqali kiritilgan o'zgarishlarni (masalan narxni
                # oshirish) keyingi deployda yo'qqa chiqarardi. Endi tarif
                # allaqachon bazada mavjud bo'lsa, unga umuman tegilmaydi — barcha
                # o'zgarishlar faqat admin panel orqali kiritiladi va doimiy
                # saqlanadi. `description` ham faqat hali bo'sh bo'lsa to'ldiriladi
                # (admin keyinchalik o'zgartirgan bo'lsa, ustidan yozilmasin).
                if not tariff.description:
                    tariff.description = data["description"]

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
