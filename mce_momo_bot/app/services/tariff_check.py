"""
Ta'rif (Tariff) maydonlarini admin panel orqali tahrirlash — TZ 5-bo'lim
(Super Admin panelini kengaytirish, "💰 Ta'riflar" bo'limi).

MUHIM: bu yerdagi o'zgarishlar darhol DB'ga yoziladi va keyingi deployda
seed.py tomonidan qayta yozib qo'yilmaydi — seed endi faqat tarif umuman
mavjud bo'lmaganda uni yaratadi, mavjud tarifga tegmaydi.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import TariffCode
from app.models.tariff import Tariff
from app.services.limits import get_tariff_by_code


class InvalidTariffFieldError(Exception):
    """Admin noto'g'ri qiymat kiritganda (masalan, son o'rniga matn)."""


def _parse_positive_int(raw: str) -> int:
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise InvalidTariffFieldError("Butun son kiriting (masalan: 3).") from exc
    if value <= 0:
        raise InvalidTariffFieldError("Musbat son bo'lishi kerak.")
    return value


def _parse_non_negative_decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation as exc:
        raise InvalidTariffFieldError("Narxni son ko'rinishida kiriting (masalan: 3000).") from exc
    if value < 0:
        raise InvalidTariffFieldError("Narx manfiy bo'lishi mumkin emas.")
    return value


def _parse_duration_days(raw: str) -> int | None:
    text = raw.strip().lower()
    if text in ("0", "yoq", "yo'q", "muddatsiz", "none", "-"):
        return None
    return _parse_positive_int(raw)


def _parse_description(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise InvalidTariffFieldError("Tavsif bo'sh bo'lishi mumkin emas.")
    if len(text) > 1000:
        raise InvalidTariffFieldError("Tavsif juda uzun (maksimum 1000 belgi).")
    return text


# Admin panelda tahrirlanadigan maydonlar: {ustun_nomi: {ko'rsatiladigan nom, validator}}
TARIFF_FIELDS: dict[str, dict] = {
    "base_hosting_price": {"label": "Hosting narxi (oyiga)", "parser": _parse_non_negative_decimal},
    "upgrade_price": {"label": "Tarifga o'tish narxi", "parser": _parse_non_negative_decimal},
    "bot_limit": {"label": "Bot soni limiti", "parser": _parse_positive_int},
    "edit_limit_per_day": {"label": "Kunlik tahrir limiti", "parser": _parse_positive_int},
    "user_threshold": {"label": "Foydalanuvchi chegarasi (narx koeffitsienti uchun)", "parser": _parse_positive_int},
    "duration_days": {"label": "Muddat, kun (0 = muddatsiz)", "parser": _parse_duration_days},
    "description": {"label": "Tavsif (ta'rif tanlashda ko'rinadi)", "parser": _parse_description},
}


async def update_tariff_field(
    session: AsyncSession, tariff_code: TariffCode, field_name: str, raw_value: str
) -> Tariff:
    """Bitta maydonni yangilaydi va darhol commit qiladi. Noto'g'ri qiymat
    kiritilsa InvalidTariffFieldError ko'taradi — DB'ga hech narsa yozilmaydi."""
    if field_name not in TARIFF_FIELDS:
        raise InvalidTariffFieldError(f"Noma'lum maydon: {field_name}")

    tariff = await get_tariff_by_code(session, tariff_code)
    parsed_value = TARIFF_FIELDS[field_name]["parser"](raw_value)
    setattr(tariff, field_name, parsed_value)
    await session.commit()
    await session.refresh(tariff)
    return tariff
