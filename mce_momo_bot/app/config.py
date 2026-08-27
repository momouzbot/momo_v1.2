"""
Markazlashtirilgan sozlamalar.
Barcha environment o'zgaruvchilar shu yerdan o'qiladi — kod ichida
qattiq (hardcode) qiymatlar yozilmaydi (TZ 6.1-bo'lim talabiga mos).
"""
from functools import lru_cache

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

    host: str = "0.0.0.0"
    port: int = 8000

    def webhook_url_for(self, bot_id: str) -> str:
        """Berilgan bot_id uchun to'liq webhook URL manzilini quradi."""
        return f"{self.base_webhook_url}{self.webhook_path_prefix}/{bot_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
