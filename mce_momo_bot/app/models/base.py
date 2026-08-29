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
    """

    type_annotation_map = {
        ModuleType: SAEnum(ModuleType, name="module_type"),
        TariffCode: SAEnum(TariffCode, name="tariff_code"),
        BotStatus: SAEnum(BotStatus, name="bot_status"),
        PaymentStatus: SAEnum(PaymentStatus, name="payment_status"),
        PaymentKind: SAEnum(PaymentKind, name="payment_kind"),
        AppealStatus: SAEnum(AppealStatus, name="appeal_status"),
        AppealCategory: SAEnum(AppealCategory, name="appeal_category"),
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
