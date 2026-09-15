"""
Barcha modellar uchun umumiy asos (declarative base) va mixinlar.
"""
import datetime
import enum

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ModuleType(str, enum.Enum):
    """TZ 3.3-bo'limidagi module_type qiymatlari."""

    ADMIN = "admin"
    SUPPORT = "support"
    KINO = "kino"
    SHOP = "shop"
    GAME_GOT = "game_got"
    GAME_MAFIA = "game_mafia"
    GAME_BUNKER = "game_bunker"
    CUSTOM = "custom"


class TariffCode(str, enum.Enum):
    """TZ 6.1-bo'limidagi tarif kodlari."""

    START = "start"
    STANDARD = "standard"
    PREMIUM = "premium"


class BotStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"          # hosting to'lanmagani uchun to'xtatilgan (6.5)
    SUSPENDED = "suspended"    # tarif muddati tugab, Start'ga tushirilgan (6.4)
    DELETED = "deleted"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PaymentKind(str, enum.Enum):
    HOSTING = "hosting"            # oylik hosting to'lovi
    TARIFF_UPGRADE = "tariff_upgrade"  # bir martalik tarifga o'tish to'lovi


class BillingPeriod(str, enum.Enum):
    """Hosting to'lovi qaysi davr uchun qilinganini bildiradi (TZ narx
    jadvali yangilanishi — mijoz haftalik yoki oylik to'lashni tanlaydi)."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AppealStatus(str, enum.Enum):
    """SupportModule uchun murojaat holati (app/models/appeal.py da ishlatiladi)."""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    ANSWERED = "answered"
    CLOSED = "closed"


class AppealCategory(str, enum.Enum):
    TECHNICAL = "technical"
    FINANCIAL = "financial"
    GENERAL = "general"


class Base(DeclarativeBase):
    """
    MUHIM: `type_annotation_map` har bir Python enum uchun PostgreSQL enum
    turining nomini ANIQ belgilaydi. Bu bo'lmasa, SQLAlchemy `Mapped[TariffCode]`
    kabi annotatsiyalar uchun avtomatik nom generatsiya qiladi (masalan
    "tariffcode" — sinf nomining pastki registri, pastki chiziqsiz), bu esa
    Alembic migratsiyalarida qo'lda yaratilgan "tariff_code" turi bilan
    MOS KELMAYDI va "type ... does not exist" xatosiga olib keladi.
    Shu sababli bu yerda nomlar migratsiya fayllaridagi (`alembic/versions/`)
    nomlar bilan so'zma-so'z bir xil bo'lishi SHART.

    YANA BIR MUHIM NUQTA: `values_callable` — SQLAlchemy standart holatda
    Python enum a'zosining NOMINI (masalan "START", katta harflar) DB'ga
    yozadi, QIYMATINI ("start", kichik harflar) emas. Bizning migratsiyamiz
    esa Postgres enum turini faqat kichik harfli qiymatlar bilan yaratgan
    ("start", "standard", "premium" va h.k.). Shu nomuvofiqlik
    "invalid input value for enum" xatosiga olib keladi. `values_callable`
    SQLAlchemy'ga aynan `.value`ni ishlatishni buyuradi — bu muammoni butunlay
    bartaraf qiladi.
    """

    type_annotation_map = {
        ModuleType: SAEnum(
            ModuleType, name="module_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        TariffCode: SAEnum(
            TariffCode, name="tariff_code", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        BotStatus: SAEnum(
            BotStatus, name="bot_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        PaymentStatus: SAEnum(
            PaymentStatus, name="payment_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        PaymentKind: SAEnum(
            PaymentKind, name="payment_kind", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        BillingPeriod: SAEnum(
            BillingPeriod, name="billing_period", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        AppealStatus: SAEnum(
            AppealStatus, name="appeal_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
        AppealCategory: SAEnum(
            AppealCategory, name="appeal_category", values_callable=lambda enum_cls: [e.value for e in enum_cls]
        ),
    }


class TimestampMixin:
    """created_at / updated_at ustunlarini avtomatik qo'shadi."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IDMixin:
    """Standart BigInteger primary key."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
