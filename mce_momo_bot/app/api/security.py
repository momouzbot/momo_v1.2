"""
Ichki boshqaruv API'lari (`/api/admin`, `/api/payments`, `/api/registration`)
uchun umumiy himoya qatlami.

MUHIM: bu uchta router faqat SIZ (loyiha egasi) yoki kelajakda qo'shiladigan
ishonchli tashqi xizmat tomonidan qo'lda/dasturiy chaqirilishi kerak — mijoz
Telegram'da botga yozganda yoki Momo Admin `/admin` orqali PIN kiritganda bu
HTTP endpointlar UMUMAN ishga tushmaydi (bot ularni chaqirmaydi, to'g'ridan-
to'g'ri Python funksiyalarini ishlatadi). Shu sababli bu tekshiruv mijoz yoki
admin uchun botda hech qanday o'zgarish keltirmaydi.

`/api/external-bots` bu tekshiruvga kirmaydi — u allaqachon har bir bot uchun
alohida `api_key` bilan himoyalangan (app/api/external_bots.py).
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.config import settings


async def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """FastAPI dependency — router darajasida ulanadi.

    Ataylab "fail closed": agar server tomonda API_SECRET_KEY sozlanmagan
    bo'lsa, HAMMA so'rov rad etiladi (503) — aksincha (kalit yo'q bo'lsa
    tekshiruvni o'tkazib yuborish) aynan avvalgi zaiflikning o'ziga olib
    kelgan edi. `hmac.compare_digest` — vaqt asosidagi hujumlarga (timing
    attack) qarshi doimiy vaqtli solishtirish uchun ishlatiladi.
    """
    if not settings.api_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Server tomonda API_SECRET_KEY sozlanmagan — bu API vaqtincha yopiq.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_secret_key):
        raise HTTPException(status_code=401, detail="Noto'g'ri yoki yo'q X-API-Key.")
