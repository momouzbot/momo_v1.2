"""
Async PostgreSQL ulanishi (SQLAlchemy 2.0 async style).
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
    connect_args={
        # Railway/PgBouncer kabi connection pooler'lar bilan asyncpg'ning
        # server-side prepared statement keshi ba'zan mos kelmay, so'rov
        # abadiy "osilib" qolishiga sabab bo'ladi. Buni o'chirish shu
        # muammoning eng keng tarqalgan yechimi hisoblanadi.
        "statement_cache_size": 0,
        # Ulanish urinishi cheksiz kutib turmasligi uchun aniq timeout —
        # muammo bo'lsa, hang o'rniga tushunarli xato chiqadi.
        "timeout": 15,
    },
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: har bir so'rov uchun alohida DB sessiyasi."""
    async with AsyncSessionLocal() as session:
        yield session
