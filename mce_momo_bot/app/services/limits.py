"""
Tarif/limit tizimi — TZ 6-bo'lim.
Bot soni limiti va kunlik tahrirlash limiti shu yerda tekshiriladi.
Kunlik hisob har kecha 00:00 (Toshkent) da reset qilinadi — sana bo'yicha
alohida qator (edit_logs.date) orqali tabiiy ravishda amalga oshadi.
"""
from __future__ import annotations

import datetime

import pytz
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BillingPeriod, BotStatus, TariffCode
from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff, EditLog
from app.models.tariff import Tariff

TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

# Start tarifidagi mijozlar uchun bot yaratilgandan keyingi birinchi shuncha
# kun hosting to'lovi talab qilinmaydi (mijoz talabi: "1-hafta hosting
# to'lovi ham bepul bo'lishi kerak").
FIRST_WEEK_FREE_DAYS = 7


def get_hosting_grace_days_remaining(bot_row: BotModel, effective_tariff: Tariff) -> int:
    """
    Start tarifidagi mijozlar uchun bot yaratilgandan keyingi FIRST_WEEK_FREE_DAYS
    kun ichida hosting to'lovi talab qilinmaydi — qolgan kunlar sonini qaytaradi
    (0 = muddat tugagan yoki mijoz Start tarifida emas, demak imtiyoz yo'q).

    MUHIM: bu faqat Start tarifiga tegishli — Standard/Premium tarifidagi
    mijozlar uchun bunday bepul davr yo'q (ular allaqachon tarif narxini
    to'lab, o'z botlarini ulashgan).
    """
    if effective_tariff.code != TariffCode.START:
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    age_days = (now - bot_row.created_at).days
    return max(0, FIRST_WEEK_FREE_DAYS - age_days)


class LimitExceededError(Exception):
    pass


def today_tashkent() -> datetime.date:
    return datetime.datetime.now(TASHKENT_TZ).date()


async def get_tariff_by_code(session: AsyncSession, code) -> Tariff:
    result = await session.execute(select(Tariff).where(Tariff.code == code))
    tariff = result.scalar_one_or_none()
    if tariff is None:
        raise LimitExceededError(f"Tarif topilmadi: {code}")
    return tariff


async def get_active_tariff(session: AsyncSession, bot_id: int) -> Tariff:
    result = await session.execute(
        select(Tariff)
        .join(BotTariff, BotTariff.tariff_code == Tariff.code)
        .where(BotTariff.bot_id == bot_id, BotTariff.is_active.is_(True))
        .limit(1)
    )
    tariff = result.scalar_one_or_none()
    if tariff is None:
        raise LimitExceededError(f"Bot uchun faol tarif topilmadi: bot_id={bot_id}")
    return tariff


async def get_active_bot_tariff(session: AsyncSession, bot_id: int) -> BotTariff:
    """get_active_tariff bilan bir xil, lekin Tariff (katalog) o'rniga BotTariff
    (bot_id, started_at, expires_at) qatorini qaytaradi — bu botning O'ZIGA
    biriktirilgan (haridi qilingan) tarifni bildiradi. Mijozga ko'rsatiladigan
    "amaldagi" tarif uchun get_owner_effective_bot_tariff() dan foydalaning —
    bu funksiya asosan ichki hisob-kitob (masalan tarif muddati nazorati)
    uchun saqlangan."""
    result = await session.execute(
        select(BotTariff)
        .where(BotTariff.bot_id == bot_id, BotTariff.is_active.is_(True))
        .limit(1)
    )
    bot_tariff = result.scalar_one_or_none()
    if bot_tariff is None:
        raise LimitExceededError(f"Bot uchun faol tarif topilmadi: bot_id={bot_id}")
    return bot_tariff


# Tarif darajalari — "eng yuqori" tarifni aniqlash uchun. bot_limit kabi
# raqamli maydonlarga emas, aynan shu tartibga tayanamiz — chunki admin
# panel orqali bot_limit/narx keyinchalik o'zgartirilishi mumkin, lekin
# Premium har doim Standard'dan, Standard esa Start'dan "yuqori" bo'lib qolishi kerak.
TARIFF_RANK: dict[TariffCode, int] = {
    TariffCode.START: 0,
    TariffCode.STANDARD: 1,
    TariffCode.PREMIUM: 2,
}


async def get_owner_effective_tariff(session: AsyncSession, owner_id: int) -> Tariff:
    """
    Mijozning HAMMA botlariga qo'llaniladigan "amaldagi" tarif.

    MUHIM QOIDA (mijoz talabi): agar mijozning istalgan bir boti
    Standard/Premium'ga oshirilgan bo'lsa, o'sha eng yuqori daraja mijozning
    BARCHA botlariga tatbiq etiladi — hatto Start tarifida ochilgan
    (hech qachon alohida oshirilmagan) botlariga ham. Amalda tarif bazada
    har bir botga alohida yozuv sifatida saqlanadi (BotTariff), lekin
    funksional cheklovlar (kunlik tahrir limiti, hosting narxi, bot soni)
    endi shu funksiya orqali — owner darajasida — aniqlanadi.
    """
    result = await session.execute(
        select(Tariff)
        .join(BotTariff, BotTariff.tariff_code == Tariff.code)
        .join(BotModel, BotModel.id == BotTariff.bot_id)
        .where(
            BotModel.owner_id == owner_id,
            BotModel.status != BotStatus.DELETED,
            BotTariff.is_active.is_(True),
        )
    )
    tariffs = result.scalars().all()
    if not tariffs:
        return await get_tariff_by_code(session, TariffCode.START)
    return max(tariffs, key=lambda t: TARIFF_RANK.get(t.code, 0))


async def get_owner_effective_bot_tariff(session: AsyncSession, owner_id: int) -> BotTariff:
    """get_owner_effective_tariff bilan bir xil mantiq, lekin BotTariff
    qatorini (tugash sanasi bilan) qaytaradi — "Botlarim" batafsil kartada
    ko'rsatish uchun. Agar mijozning bir nechta boti bir xil eng yuqori
    darajada bo'lsa — ulardan biri qaytariladi (amalda deyarli har doim
    faqat bitta bot haqiqiy xarid qilingan tarifga ega bo'ladi)."""
    result = await session.execute(
        select(BotTariff)
        .join(BotModel, BotModel.id == BotTariff.bot_id)
        .where(
            BotModel.owner_id == owner_id,
            BotModel.status != BotStatus.DELETED,
            BotTariff.is_active.is_(True),
        )
    )
    bot_tariffs = result.scalars().all()
    if not bot_tariffs:
        raise LimitExceededError(f"Mijoz uchun faol tarif topilmadi: owner_id={owner_id}")
    return max(bot_tariffs, key=lambda bt: TARIFF_RANK.get(bt.tariff_code, 0))


async def get_owner_bot_limit(session: AsyncSession, owner_id: int) -> int:
    """Mijoz YANGI bot yaratishi mumkin bo'lgan limit — amaldagi (eng yuqori)
    tarifga qarab (bot hali umuman yo'q bo'lsa — Start limiti)."""
    tariff = await get_owner_effective_tariff(session, owner_id)
    return tariff.bot_limit


async def check_bot_limit(session: AsyncSession, owner_id: int, bot_limit: int) -> None:
    """
    Mijozning faol botlari soni berilgan limitdan oshmasligini tekshiradi (TZ 6.1).

    MUHIM TUZATISH: avval o'chirilgan (DELETED) botlar ham hisoblanardi —
    mijoz botini o'chirsa ham, limit "band" bo'lib qolaverardi. Endi faqat
    DELETED bo'lmagan botlar hisoblanadi.

    `bot_limit` — chaqiruvchi tomon aniqlab beradi (odatda
    `get_owner_bot_limit()` orqali), chunki tarif har bir botga alohida
    biriktirilgan va to'g'ri limitni tanlash chaqiruvchining vazifasi.
    """
    result = await session.execute(
        select(func.count())
        .select_from(BotModel)
        .where(BotModel.owner_id == owner_id, BotModel.status != BotStatus.DELETED)
    )
    active_count = result.scalar_one()
    if active_count >= bot_limit:
        raise LimitExceededError(f"Bot limiti to'lgan: {active_count}/{bot_limit}")


async def check_and_increment_edit_limit(session: AsyncSession, bot_id: int) -> None:
    """
    Yangi funksional panel/modul elementi qo'shishdan oldin chaqiriladi (TZ 6.2).
    Limitga yetgan bo'lsa LimitExceededError ko'taradi, aks holda hisoblagichni +1 qiladi.

    MUHIM: limit botning O'ZINING tarifi emas, balki mijozning AMALDAGI (eng
    yuqori) tarifi bo'yicha aniqlanadi — Premium mijozning barcha botlari,
    hatto Start'da ochilganlari ham, Premium darajasidagi kunlik limitdan
    foydalanadi.
    """
    owner_result = await session.execute(select(BotModel.owner_id).where(BotModel.id == bot_id))
    owner_id = owner_result.scalar_one_or_none()
    if owner_id is None:
        raise LimitExceededError(f"Bot topilmadi: bot_id={bot_id}")

    tariff = await get_owner_effective_tariff(session, owner_id)
    today = today_tashkent()

    result = await session.execute(
        select(EditLog).where(EditLog.bot_id == bot_id, EditLog.date == today)
    )
    log_row = result.scalar_one_or_none()

    current_count = log_row.count if log_row else 0
    if current_count >= tariff.edit_limit_per_day:
        raise LimitExceededError(
            f"Kunlik tahrirlash limiti tugagan: {current_count}/{tariff.edit_limit_per_day}"
        )

    if log_row is None:
        session.add(EditLog(bot_id=bot_id, date=today, count=1))
    else:
        log_row.count = current_count + 1

    await session.commit()


async def calculate_hosting_price(
    session: AsyncSession, bot_id: int, unique_user_count: int, billing_period: BillingPeriod
) -> float:
    """
    1000 user chegarasi formulasi (TZ 6.3):
        koeffitsient = floor(user_soni / 1000) + 1
        narx = (haftalik yoki oylik bazaviy narx) * koeffitsient

    MUHIM: narx botning O'ZINING tarifi emas, balki mijozning AMALDAGI (eng
    yuqori) tarifi bo'yicha hisoblanadi — Premium mijozning barcha botlari
    Premium darajasidagi (odatda arzonroq) hosting narxidan foydalanadi.
    """
    owner_result = await session.execute(select(BotModel.owner_id).where(BotModel.id == bot_id))
    owner_id = owner_result.scalar_one_or_none()
    if owner_id is None:
        raise LimitExceededError(f"Bot topilmadi: bot_id={bot_id}")

    tariff = await get_owner_effective_tariff(session, owner_id)
    coefficient = (unique_user_count // tariff.user_threshold) + 1
    base_price = tariff.weekly_hosting_price if billing_period == BillingPeriod.WEEKLY else tariff.base_hosting_price
    return float(base_price) * coefficient


async def get_unique_user_count(session: AsyncSession, bot_id: int) -> int:
    """
    Noyob foydalanuvchilar soni (TZ 6.3):
        - Momo o'zi hostinglaydigan botlar uchun — bot_users jadvalidan hisoblanadi
        - Tashqi hostingdagi botlar uchun (masalan GOT Game) — bot o'zi hisobot
          bergan `external_user_count` qiymati ishlatiladi (bot_users bo'sh
          qoladi, chunki update'lar Momo dispatcheriga umuman kelmaydi)
    """
    from app.models.bot import Bot as BotModel
    from app.models.bot import BotUser

    bot_result = await session.execute(select(BotModel).where(BotModel.id == bot_id))
    bot_row = bot_result.scalar_one_or_none()
    if bot_row is None:
        raise LimitExceededError(f"Bot topilmadi: bot_id={bot_id}")

    if bot_row.is_externally_hosted:
        return bot_row.external_user_count

    result = await session.execute(
        select(func.count()).select_from(BotUser).where(BotUser.bot_id == bot_id)
    )
    return result.scalar_one()
