"""
Alembic env.py — async SQLAlchemy bilan ishlash uchun moslashtirilgan.
DATABASE_URL app.config.settings orqali olinadi (hardcode qilinmagan).
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models import Base  # barcha modellarni import qiladi -> metadata to'liq bo'ladi

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# alembic.ini dagi bo'sh sqlalchemy.url o'rniga runtime'dagi haqiqiy DATABASE_URL qo'yiladi
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # MUHIM: async_engine_from_config o'rniga to'g'ridan-to'g'ri create_async_engine
    # ishlatiladi — shunda connect_args orqali asyncpg sozlamalarini berish mumkin.
    # Railway kabi platformalarda PgBouncer/connection pooler bilan asyncpg'ning
    # server-side prepared statement keshi ba'zan mos kelmay, ulanish/so'rov
    # abadiy "osilib" qolishiga sabab bo'ladi (statement_cache_size=0 buni oldini
    # oladi). `timeout` esa ulanish muammosi bo'lganda cheksiz kutish o'rniga
    # tushunarli xato chiqarish uchun.
    print("[MIGRATION-DEBUG] Engine yaratilmoqda...", flush=True)
    connectable = create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,
        connect_args={
            "statement_cache_size": 0,
            "timeout": 15,
        },
    )
    print("[MIGRATION-DEBUG] Engine yaratildi. Ulanish ochilmoqda...", flush=True)

    try:
        async with asyncio.timeout(30):
            async with connectable.connect() as connection:
                print("[MIGRATION-DEBUG] Ulanish OCHILDI. Migratsiya ishga tushmoqda...", flush=True)
                await connection.run_sync(do_run_migrations)
                print("[MIGRATION-DEBUG] Migratsiya TUGADI.", flush=True)
    except TimeoutError:
        print("[MIGRATION-DEBUG] XATO: 30 soniyada tugamadi — TIMEOUT!", flush=True)
        raise
    except Exception as exc:
        print(f"[MIGRATION-DEBUG] XATO: {type(exc).__name__}: {exc}", flush=True)
        raise

    print("[MIGRATION-DEBUG] Engine yopilmoqda...", flush=True)
    await connectable.dispose()
    print("[MIGRATION-DEBUG] Hammasi tugadi.", flush=True)


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
