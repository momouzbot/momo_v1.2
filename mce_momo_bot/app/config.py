"""
Markazlashtirilgan sozlamalar.
Barcha environment o'zgaruvchilar shu yerdan o'qiladi — kod ichida
qattiq (hardcode) qiymatlar yozilmaydi (TZ 6.1-bo'lim talabiga mos).
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    base_webhook_url: str = "https://domain.uz"
    webhook_path_prefix: str = "/webhook"

    momo_bot_token: str = ""

    # Mijoz bot tokenlarini shifrlash uchun Fernet kaliti (base64, 32 bayt).
    # Generatsiya: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = ""

    database_url: str = "postgresql+asyncpg://mce_user:mce_pass@localhost:5432/mce_momo"

    redis_url: str = "redis://localhost:6379/0"

    scheduler_timezone: str = "Asia/Tashkent"

    # Birinchi Momo Admin'ni avtomatik belgilash uchun (TZ 8-bo'lim: Momo Admin roli).
    # Shu Telegram ID'li foydalanuvchi Momo botga /start bosganda avtomatik
    # is_momo_admin=True qilib belgilanadi. Faqat siz (loyiha egasi) shu
    # o'zgaruvchini bilasiz — boshqa hech kim o'zini admin qila olmaydi.
    super_admin_telegram_id: int | None = None

    # Qo'shimcha xavfsizlik qatlami: /admin panelini ochishda so'raladigan
    # maxfiy PIN kod. Railway Variables'da ADMIN_PIN sifatida saqlanadi va
    # kodning hech bir joyida hardcode qilinmaydi. Bo'sh qoldirilsa (default),
    # PIN so'ralmaydi — faqat is_momo_admin tekshiruvi bilan cheklanadi
    # (orqaga muvofiqlik uchun), lekin ishlab chiqarishda to'ldirish tavsiya etiladi.
    admin_pin: str = ""

    # Ichki boshqaruv API'lari (/api/admin, /api/payments, /api/registration)
    # uchun umumiy maxfiy kalit. Har bir so'rov `X-API-Key` sarlavhasida shu
    # qiymatni yuborishi shart, aks holda 401/503 bilan rad etiladi. Railway
    # Variables'da API_SECRET_KEY sifatida saqlanadi, kodda hardcode qilinmaydi.
    # /api/external-bots bunga kirmaydi — u har bot uchun alohida api_key
    # bilan allaqachon himoyalangan.
    api_secret_key: str = ""

    host: str = "0.0.0.0"
    port: int = 8000

    @field_validator("database_url")
    @classmethod
    def _ensure_asyncpg_driver(cls, v: str) -> str:
        """
        Railway/Heroku kabi platformalar Postgres qo'shimchasini ulaganda
        DATABASE_URL'ni odatda `postgres://` yoki `postgresql://` sxemasida
        beradi — bizga esa async ishlash uchun `postgresql+asyncpg://` kerak.
        Shu sababli avtomatik ravishda drayver nomi to'g'rilanadi, foydalanuvchi
        Railway'da qo'lda o'zgartirishi shart emas.
        """
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    def webhook_url_for(self, bot_id: str) -> str:
        """Berilgan bot_id uchun to'liq webhook URL manzilini quradi."""
        return f"{self.base_webhook_url}{self.webhook_path_prefix}/{bot_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
