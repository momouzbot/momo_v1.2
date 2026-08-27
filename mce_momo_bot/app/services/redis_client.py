"""
Redis — cache/rate-limit/kunlik hisob (TZ 2.1-bo'lim).
Masalan: tahrirlash limitini tez tekshirish uchun kunlik hisoblagich,
Telegram rate-limit navbati (TZ 11-bo'lim: 1 msg/sek/chat, 30 msg/sek global).
"""
from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from app.config import settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)
