"""
bots, bot_users, bot_tariffs, edit_logs — TZ 9-bo'lim.
"""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BotStatus, IDMixin, ModuleType, TariffCode, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Bot(Base, IDMixin, TimestampMixin):
    """Ro'yxatdan o'tgan mijoz boti (TZ 9-bo'lim: bots jadvali)."""

    __tablename__ = "bots"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Telegram tomonidagi bot identifikatori (masalan 123456789 — bot_id sifatida
    # webhook path'ida ishlatiladi: /webhook/{bot_id})
    telegram_bot_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)

    # Token shifrlangan holda saqlanishi tavsiya etiladi (masalan Fernet bilan);
    # bu yerda ustun nomi shunga ishora qiladi.
    token_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)

    module_type: Mapped[ModuleType] = mapped_column(nullable=False)
    status: Mapped[BotStatus] = mapped_column(default=BotStatus.ACTIVE, nullable=False)

    webhook_set: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Core (umumiy) sozlamalar — TZ 3.2-bo'lim ---
    force_subscribe_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    force_subscribe_channels: Mapped[list[str] | None] = mapped_column(
        String, nullable=True
    )  # JSON/CSV ko'rinishida kanal ro'yxati; keyinchalik alohida jadvalga chiqarilishi mumkin
    captcha_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    welcome_message: Mapped[str | None] = mapped_column(String, nullable=True)
    spam_filter_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Murojaat/buyurtma kabi hodisalarni forward qilish uchun admin guruh/kanal ID'si
    # (SupportModule, ShopModule va boshqalar tomonidan ishlatiladi).
    admin_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # --- Tashqi hostingdagi botlar uchun (masalan GOT Game) ---
    # Bot boshqa serverda ishlaydi, Momo faqat tarif/trafik nazoratini oladi:
    # webhook Momo tomonidan o'rnatilmaydi, update'lar Momo dispatcheriga kelmaydi.
    is_externally_hosted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Tashqi bot trafik hisobotini yuborishda o'zini tasdiqlashi uchun maxfiy kalit
    external_api_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Tashqi bot tomonidan oxirgi marta hisobot berilgan noyob foydalanuvchilar soni
    # (hosting narxini hisoblashda bot_users o'rniga shu qiymat ishlatiladi)
    external_user_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="bots")
    tariff_history: Mapped[list["BotTariff"]] = relationship(back_populates="bot")


class BotUser(Base, IDMixin):
    """
    bot_users — bot bo'yicha noyob /start bosgan foydalanuvchilar (1000 limit uchun, TZ 6.3).
    Kanal/guruh a'zolari EMAS — faqat dialog boshlaganlar.
    """

    __tablename__ = "bot_users"
    __table_args__ = (UniqueConstraint("bot_id", "telegram_user_id", name="uq_bot_user"),)

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BotTariff(Base, IDMixin, TimestampMixin):
    """bot_tariffs — bot_id, tarif turi, boshlangan/tugash sana, holat (TZ 9-bo'lim)."""

    __tablename__ = "bot_tariffs"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    tariff_code: Mapped[TariffCode] = mapped_column(nullable=False)
    started_at: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    expires_at: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)  # Start uchun NULL (muddatsiz)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    bot: Mapped["Bot"] = relationship(back_populates="tariff_history")


class EditLog(Base, IDMixin):
    """
    edit_logs — kunlik tahrirlash hisobi (bot_id, sana, count), TZ 6.2-bo'lim.
    Faqat "yangi funksional panel/modul elementi qo'shish" shu yerga hisoblanadi.
    Har kecha 00:00 (Toshkent) da kunlik hisob nol boshlanadi (yangi sana qatori).
    """

    __tablename__ = "edit_logs"
    __table_args__ = (UniqueConstraint("bot_id", "date", name="uq_bot_edit_date"),)

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
