"""
Sub-adminlar (yordamchi moderatorlar) — bot egasi ularga o'z botida kontent
boshqarish huquqini bera oladi (masalan kino qo'shish/o'chirish, murojaatga
javob berish). Bot sozlamalari (majburiy kanal, ommaviy xabar) va
sub-adminlarni boshqarishning O'ZI esa faqat haqiqiy egaga tegishli. Barcha
modullarda umumiy (core) funksiya
(app/modules/base.py::register_core_features orqali avtomatik ulanadi).

Qat'iy limit: bot boshiga maksimum 3 ta sub-admin.

/moderatorlar — FAQAT bot egasi uchun (is_bot_owner — sub-adminning o'zi
boshqa sub-admin qo'sha olmaydi):
    - joriy sub-adminlar ro'yxati + o'chirish tugmalari
    - ➕ qo'shish — sub-admin qilinadigan odamdan xabar forward qilish
      so'raladi (Telegram bot @username orqali begona foydalanuvchini
      qidira olmaydi, shuning uchun forward — yagona ishonchli usul; xuddi
      channel_settings.py dagi kanal qo'shish kabi)
"""
from __future__ import annotations

import logging

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import Bot as BotModel
from app.models.sub_admin import BotSubAdmin
from app.services.ownership import is_bot_owner
from app.services.sub_admins import (
    SUB_ADMIN_LIMIT,
    SubAdminAlreadyExistsError,
    SubAdminLimitError,
    add_sub_admin,
    list_sub_admins,
    remove_sub_admin,
)

logger = logging.getLogger(__name__)


class SubAdminStates(StatesGroup):
    waiting_for_forward = State()


def _format_list_text(sub_admins: list[BotSubAdmin]) -> str:
    if not sub_admins:
        return (
            "👥 Yordamchi moderatorlar\n\n"
            "Hozircha sub-admin yo'q. Ular sizga kontent boshqarishda "
            "(masalan kino qo'shish, murojaatlarga javob berish) yordam "
            f"bera oladi. Maksimum {SUB_ADMIN_LIMIT} ta."
        )
    lines = ["👥 Yordamchi moderatorlar\n"]
    for sa in sub_admins:
        name = sa.full_name or str(sa.telegram_user_id)
        lines.append(f"• {name}")
    lines.append(f"\n({len(sub_admins)}/{SUB_ADMIN_LIMIT})")
    return "\n".join(lines)


def _list_keyboard(sub_admins: list[BotSubAdmin]):
    builder = InlineKeyboardBuilder()
    for sa in sub_admins:
        name = sa.full_name or str(sa.telegram_user_id)
        builder.button(text=f"➖ {name}", callback_data=f"subadmin_remove:{sa.telegram_user_id}")
    if len(sub_admins) < SUB_ADMIN_LIMIT:
        builder.button(text="➕ Sub-admin qo'shish", callback_data="subadmin_add")
    builder.adjust(1)
    return builder.as_markup()


def register_sub_admins(dp: Dispatcher, bot_row: BotModel) -> None:
    router = Router(name="core_sub_admins")

    async def _require_owner(session: AsyncSession, telegram_id: int) -> bool:
        return await is_bot_owner(session, bot_row.id, telegram_id)

    @router.message(Command("moderatorlar"))
    async def cmd_sub_admins(message: Message, session: AsyncSession, state: FSMContext) -> None:
        if not await _require_owner(session, message.from_user.id):
            return  # sub-adminga ham, oddiy foydalanuvchiga ham ko'rinmasligi kerak
        await state.clear()
        sub_admins = await list_sub_admins(session, bot_row.id)
        await message.answer(_format_list_text(sub_admins), reply_markup=_list_keyboard(sub_admins))

    @router.callback_query(F.data == "subadmin_add")
    async def on_add_start(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
        if not await _require_owner(session, callback.from_user.id):
            await callback.answer()
            return

        sub_admins = await list_sub_admins(session, bot_row.id)
        if len(sub_admins) >= SUB_ADMIN_LIMIT:
            await callback.answer(f"Limit to'lgan: {SUB_ADMIN_LIMIT}/{SUB_ADMIN_LIMIT}", show_alert=True)
            return

        await state.set_state(SubAdminStates.waiting_for_forward)
        await callback.message.answer(
            "Sub-admin qilmoqchi bo'lgan kishidan biror xabarni shu yerga forward qiling.\n\n"
            "⚠️ O'sha kishi avval botingizga /start bosgan bo'lishi kerak.\n"
            "Bekor qilish uchun /bekor."
        )
        await callback.answer()

    @router.message(SubAdminStates.waiting_for_forward, Command("bekor"))
    async def on_add_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Bekor qilindi.")

    @router.message(SubAdminStates.waiting_for_forward)
    async def on_forward_received(message: Message, session: AsyncSession, state: FSMContext) -> None:
        if not await _require_owner(session, message.from_user.id):
            await state.clear()
            return

        if message.forward_from is None:
            await message.answer(
                "Tushunmadim. Iltimos, o'sha kishidan biror xabarni forward qiling "
                "(agar u shaxsiy sozlamalarida forward qilishni yashirgan bo'lsa, "
                "afsuski uni shu usulda sub-admin qilib bo'lmaydi). "
                "Bekor qilish uchun /bekor."
            )
            return

        target = message.forward_from
        try:
            await add_sub_admin(session, bot_row.id, target.id, message.from_user.id, target.full_name)
        except SubAdminAlreadyExistsError:
            await message.answer("Bu foydalanuvchi allaqachon sub-admin.")
            await state.clear()
            return
        except SubAdminLimitError as exc:
            await message.answer(f"❌ {exc}")
            await state.clear()
            return

        await state.clear()
        sub_admins = await list_sub_admins(session, bot_row.id)
        await message.answer(
            f"✅ {target.full_name} sub-admin qilib tayinlandi.\n\n{_format_list_text(sub_admins)}",
            reply_markup=_list_keyboard(sub_admins),
        )

    @router.callback_query(F.data.startswith("subadmin_remove:"))
    async def on_remove(callback: CallbackQuery, session: AsyncSession) -> None:
        if not await _require_owner(session, callback.from_user.id):
            await callback.answer()
            return

        telegram_user_id = int(callback.data.split(":", 1)[1])
        await remove_sub_admin(session, bot_row.id, telegram_user_id)

        sub_admins = await list_sub_admins(session, bot_row.id)
        await callback.answer("Olib tashlandi.")
        await callback.message.edit_text(_format_list_text(sub_admins), reply_markup=_list_keyboard(sub_admins))

    dp.include_router(router)
