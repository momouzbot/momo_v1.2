"""
Platforma sozlamalari (hozircha to'lov rekvizitlari) — singleton qator.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_settings import PlatformSettings


async def get_platform_settings(session: AsyncSession) -> PlatformSettings:
    result = await session.execute(select(PlatformSettings).limit(1))
    settings_row = result.scalar_one_or_none()
    if settings_row is None:
        settings_row = PlatformSettings()
        session.add(settings_row)
        await session.commit()
        await session.refresh(settings_row)
    return settings_row


async def update_payment_details(
    session: AsyncSession, card_number: str | None, card_holder: str | None, instructions: str | None
) -> PlatformSettings:
    settings_row = await get_platform_settings(session)
    settings_row.payment_card_number = card_number
    settings_row.payment_card_holder = card_holder
    settings_row.payment_instructions = instructions
    await session.commit()
    await session.refresh(settings_row)
    return settings_row


def format_payment_details(settings_row: PlatformSettings) -> str:
    if not settings_row.payment_card_number:
        return "⚠️ To'lov rekvizitlari hali sozlanmagan. Admin bilan bog'laning."

    lines = [f"💳 Karta raqami: {settings_row.payment_card_number}"]
    if settings_row.payment_card_holder:
        lines.append(f"👤 Karta egasi: {settings_row.payment_card_holder}")
    if settings_row.payment_instructions:
        lines.append(f"\nℹ️ {settings_row.payment_instructions}")
    return "\n".join(lines)
