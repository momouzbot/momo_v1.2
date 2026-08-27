"""
Lokal ishga tushirish uchun entrypoint.
Production'da: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
(Eslatma: BotRegistry xotirada saqlanadi, shu sababli hozircha 1 worker —
TZ 2.1 izohiga qarang. Ko'p worker uchun shared-cache yechimi kerak.)
"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.app_env == "development",
    )
