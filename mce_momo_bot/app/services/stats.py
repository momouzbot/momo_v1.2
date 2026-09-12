"""
Admin panel uchun umumiy statistika — TZ 5-bo'lim (Super Admin panelini
kengaytirish, "📊 Statistika" bo'limi).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import PaymentStatus
from app.models.bot import Bot as BotModel
from app.models.bot import BotTariff
from app.models.payment import Payment
from app.models.user import User


async def get_platform_stats(session: AsyncSession) -> dict:
    users_count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    bots_count = (await session.execute(select(func.count()).select_from(BotModel))).scalar_one()

    status_rows = await session.execute(select(BotModel.status, func.count()).group_by(BotModel.status))
    status_counts = dict(status_rows.all())

    tariff_rows = await session.execute(
        select(BotTariff.tariff_code, func.count())
        .where(BotTariff.is_active.is_(True))
        .group_by(BotTariff.tariff_code)
    )
    tariff_counts = dict(tariff_rows.all())

    pending_payments = (
        await session.execute(
            select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.PENDING)
        )
    ).scalar_one()

    return {
        "users_count": users_count,
        "bots_count": bots_count,
        "status_counts": status_counts,
        "tariff_counts": tariff_counts,
        "pending_payments": pending_payments,
    }
