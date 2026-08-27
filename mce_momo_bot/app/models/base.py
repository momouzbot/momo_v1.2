"""
Barcha modellar uchun umumiy asos (declarative base) va mixinlar.
"""
import datetime
import enum

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
