"""
Majburiy kanal(lar)ni bot egasining O'ZI boshqarishi — barcha modullarda
umumiy (core) funksiya (app/modules/base.py::register_core_features orqali
har bir modulga avtomatik ulanadi, alohida-alohida yozish shart emas).

Mijoz talabi: "har bir modulda mijoz admin o'z botiga majburiy kanal ulash
yoki o'chirish funksiyasini qo'sha olishi kerak, bu amal kunlik tahrirlash
limitiga kiradi" — ya'ni har bir qo'shish/o'chirish amali
Tariff.edit_limit_per_day limitidan bittasini sarflaydi (xuddi kino
qo'shish kabi — app/services/limits.py::check_and_increment_edit_limit).

/kanallar — faqat bot egasi uchun (is_bot_owner):
    - joriy majburiy kanallar ro'yxatini ko'rsatadi
    - ➕ Kanal qo'shish — kanal username'i (@kanal) yoki o'sha kanaldan
      forward qilingan xabar so'raladi; bot o'sha kanalda ADMIN ekani
      tekshiriladi (aks holda keyinchalik obunani tekshira olmaydi)
    - ➖ Kanal olib tashlash — ro'yxatdan birini tanlab o'chiradi

MUHIM: o'zgarish bazaga yozilishi bilan bir qatorda, xotiradagi (joriy
ishlab turgan) `bot_row` obyektining o'zi ham yangilanadi — chunki
ForceSubscribeMiddleware AYNAN shu obyektga ishora qiladi (dispatcher/
registry.py orqali bot ishga tushganda bir marta yuklanadi va keshda
turadi). Shu sababli bot qayta ishga tushirilmasdan turib o'zgarish
darhol kuchga kiradi.
"""
from __future__ import annotations

import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.force_subscribe import parse_force_subscribe_channels
from app.models.bot import Bot as BotModel
from app.services.limits import LimitExceededError, check_and_increment_edit_limit
from app.services.ownership import is_bot_owner

logger = logging.getLogger(__name__)


class ChannelSettingsStates(StatesGroup):
    waiting_for_channel = State()


def _channels_keyboard(channels: list[str]):
    builder = InlineKeyboardBuilder()
    for channel in channels:
        builder.button(text=f"➖ {channel}", callback_data=f"chsettings_remove:{channel}")
    builder.button(text="➕ Kanal qo'shish", callback_data="chsettings_add")
    builder.adjust(1)
    return builder.as_markup()


def _format_channels_text(channels: list[str]) -> str:
    if not channels:
        return (
            "📢 Majburiy obuna kanallari\n\n"
            "Hozircha hech qanday kanal ulanmagan — botingizdan foydalanish "
            "uchun foydalanuvchilar majburiy obuna bo'lishi shart emas."
        )
    lines = ["📢 Majburiy obuna kanallari\n"] + [f"• {c}" for c in channels]
    lines.append("\nFoydalanuvchilar botdan foydalanishdan oldin shu kanallarga obuna bo'lishi shart.")
    return "\n".join(lines)


def _persist_channels(bot_row: BotModel, channels: list[str]) -> None:
    """Xotiradagi bot_row'ni HAM, keyin chaqiruvchi tomon DB'ga ham yozadi.
    Tartib muhim: avval xotira (middleware darhol ko'rsin), keyin commit."""
    bot_row.force_subscribe_channels = ",".join(channels) if channels else None
    bot_row.force_subscribe_enabled = bool(channels)


async def _resolve_channel_identifier(message: Message) -> str | None:
    """Foydalanuvchi yuborgan matn (@kanal) yoki forward qilingan xabardan
    kanal identifikatorini chiqarib oladi. Faqat ochiq (username'li)
    kanallar qo'llab-quvvatlanadi — force_subscribe tugmalari t.me/username
    havolasiga tayanadi."""
    if message.forward_from_chat is not None and message.forward_from_chat.username:
        return f"@{message.forward_from_chat.username}"

    text = (message.text or "").strip()
    if not text:
        return None
    if text.startswith("https://t.me/"):
        text = text.removeprefix("https://t.me/")
    elif text.startswith("t.me/"):
        text = text.removeprefix("t.me/")
    text = text.lstrip("@").strip()
    if not text:
        return None
    return f"@{text}"


def register_channel_settings(dp: Dispatcher, bot_row: BotModel) -> None:
    router = Router(name="core_channel_settings")

    async def _require_owner(session: AsyncSession, telegram_id: int) -> bool:
        return await is_bot_owner(session, bot_row.id, telegram_id)

    @router.message(Command("kanallar"))
    async def cmd_channels(message: Message, session: AsyncSession, state: FSMContext) -> None:
        if not await _require_owner(session, message.from_user.id):
            return  # oddiy foydalanuvchiga bu buyruq umuman ko'rinmasligi kerak
        await state.clear()
        channels = parse_force_subscribe_channels(bot_row)
        await message.answer(_format_channels_text(channels), reply_markup=_channels_keyboard(channels))

    @router.callback_query(F.data == "chsettings_add")
    async def on_add_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
        if not await _require_owner(session, callback.from_user.id):
            await callback.answer()
            return
        await state.set_state(ChannelSettingsStates.waiting_for_channel)
        await callback.message.answer(
            "Kanal username'ini yuboring (masalan @mening_kanalim) yoki "
            "o'sha kanaldan istalgan xabarni forward qiling.\n\n"
            "⚠️ Botni OLDIN o'sha kanalga ADMIN qilib qo'shing — aks holda "
            "bot foydalanuvchilarning obunasini tekshira olmaydi."
        )
        await callback.answer()

    @router.message(ChannelSettingsStates.waiting_for_channel, Command("bekor"))
    async def on_add_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Bekor qilindi.")

    @router.message(ChannelSettingsStates.waiting_for_channel)
    async def on_channel_received(
        message: Message, session: AsyncSession, state: FSMContext, bot: AiogramBot
    ) -> None:
        if not await _require_owner(session, message.from_user.id):
            await state.clear()
            return

        channel = await _resolve_channel_identifier(message)
        if channel is None:
            await message.answer(
                "Tushunmadim. Kanal username'ini yuboring (masalan @mening_kanalim) "
                "yoki kanaldan xabar forward qiling. Bekor qilish uchun /bekor."
            )
            return

        channels = parse_force_subscribe_channels(bot_row)
        if channel in channels:
            await message.answer(f"{channel} allaqachon ro'yxatda bor.")
            await state.clear()
            return

        try:
            me = await bot.get_me()
            member = await bot.get_chat_member(chat_id=channel, user_id=me.id)
            if member.status not in ("administrator", "creator"):
                raise ValueError("not admin")
        except Exception:
            await message.answer(
                f"❌ Bot {channel} kanalida ADMIN emas (yoki kanal topilmadi). "
                "Avval botni o'sha kanalga admin qilib qo'shing, so'ng qayta yuboring."
            )
            return

        try:
            await check_and_increment_edit_limit(session, bot_row.id)
        except LimitExceededError as exc:
            await message.answer(f"❌ Kunlik tahrirlash limitiga yetdingiz: {exc}")
            await state.clear()
            return

        channels.append(channel)
        _persist_channels(bot_row, channels)
        await session.commit()

        await state.clear()
        await message.answer(
            f"✅ {channel} qo'shildi.\n\n{_format_channels_text(channels)}",
            reply_markup=_channels_keyboard(channels),
        )

    @router.callback_query(F.data.startswith("chsettings_remove:"))
    async def on_remove(callback: CallbackQuery, session: AsyncSession) -> None:
        if not await _require_owner(session, callback.from_user.id):
            await callback.answer()
            return

        channel = callback.data.split(":", 1)[1]
        channels = parse_force_subscribe_channels(bot_row)
        if channel not in channels:
            await callback.answer("Bu kanal ro'yxatda topilmadi.", show_alert=True)
            return

        try:
            await check_and_increment_edit_limit(session, bot_row.id)
        except LimitExceededError as exc:
            await callback.answer(f"Kunlik tahrirlash limitiga yetdingiz: {exc}", show_alert=True)
            return

        channels.remove(channel)
        _persist_channels(bot_row, channels)
        await session.commit()

        await callback.answer(f"{channel} olib tashlandi.")
        await callback.message.edit_text(_format_channels_text(channels), reply_markup=_channels_keyboard(channels))

    dp.include_router(router)
