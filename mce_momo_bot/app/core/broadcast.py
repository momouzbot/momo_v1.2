"""
Ommaviy xabar (broadcast) — bot egasi o'z botining barcha foydalanuvchilariga
xabar yuborishi mumkin. Barcha modullarda umumiy (core) funksiya
(app/modules/base.py::register_core_features orqali avtomatik ulanadi).

Mijoz talabi: "Ommaviy xabar yuborish — 1/kun — ko'p resurs sarf qilgani
sabab qat'iy cheklangan" — bu MOMO TARIFIDAN MUSTAQIL, hamma uchun bir xil
kunlik limit (app/services/feature_limits.py orqali — Tariff.edit_limit_per_day
BILAN EMAS, chunki bu alohida, resurs jihatidan og'ir amal).

/xabar — faqat bot egasi uchun (is_bot_owner):
    1. Xabar mazmunini (matn/rasm/video + izoh) so'raydi
    2. Necha foydalanuvchiga ketishini ko'rsatib tasdiqlashni so'raydi
    3. Tasdiqlangach — FON VAZIFASI (asyncio background task) sifatida
       yuboradi, webhook javobini bloklamaydi. Har xabar orasida kichik
       pauza — Telegram flood-limitiga tegmaslik uchun.
    4. Yakunlangach bot egasiga natija hisobotini yuboradi va BroadcastLog
       yozuviga saqlaydi (Momo bot orqali "statistika ko'rish" shu yerdan
       o'qiydi).
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.bot import Bot as BotModel
from app.models.bot import BotUser
from app.models.broadcast import BroadcastLog
from app.services.feature_limits import check_and_increment_feature_limit
from app.services.limits import LimitExceededError
from app.services.ownership import is_bot_owner

logger = logging.getLogger(__name__)

BROADCAST_FEATURE_KEY = "ommaviy_xabar"
BROADCAST_DAILY_LIMIT = 1
_SEND_DELAY_SECONDS = 0.05  # ~20 xabar/soniya — Telegram flood-limitiga tegmaslik uchun


class BroadcastStates(StatesGroup):
    waiting_for_content = State()
    waiting_for_confirm = State()


def _confirm_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yuborish", callback_data="broadcast_confirm")
    builder.button(text="❌ Bekor qilish", callback_data="broadcast_cancel")
    builder.adjust(2)
    return builder.as_markup()


async def _run_broadcast(
    bot: AiogramBot, bot_id: int, owner_telegram_id: int, from_chat_id: int, message_id: int
) -> None:
    """Fon vazifasi — webhook javobini bloklamaslik uchun asyncio.create_task
    orqali ishga tushiriladi, shuning uchun o'z sessiyasini ochadi (request
    sessiyasi javob qaytarilgach yopiladi, uni qayta ishlatib bo'lmaydi)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BotUser.telegram_user_id).where(BotUser.bot_id == bot_id))
        user_ids = [row[0] for row in result.all()]

        success = 0
        failed = 0
        for user_id in user_ids:
            try:
                await bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)
                success += 1
            except TelegramForbiddenError:
                failed += 1  # bloklagan yoki botni o'chirgan
            except Exception:
                failed += 1
                logger.exception("Broadcast xabarini yuborishda xato: user_id=%s", user_id)
            await asyncio.sleep(_SEND_DELAY_SECONDS)

        session.add(
            BroadcastLog(
                bot_id=bot_id,
                sent_by_telegram_id=owner_telegram_id,
                total_recipients=len(user_ids),
                success_count=success,
                failed_count=failed,
            )
        )
        await session.commit()

    try:
        await bot.send_message(
            owner_telegram_id,
            "📬 Ommaviy xabar yuborish yakunlandi.\n\n"
            f"👥 Jami: {len(user_ids)} ta\n"
            f"✅ Yetib bordi: {success} ta\n"
            f"❌ Yetmadi: {failed} ta (bloklagan yoki botni o'chirgan bo'lishi mumkin)",
        )
    except Exception:
        logger.exception("Broadcast yakun xabarini yuborishda xato")


def register_broadcast(dp: Dispatcher, bot_row: BotModel) -> None:
    router = Router(name="core_broadcast")

    async def _require_owner(session: AsyncSession, telegram_id: int) -> bool:
        return await is_bot_owner(session, bot_row.id, telegram_id)

    @router.message(Command("xabar"))
    async def cmd_broadcast(message: Message, session: AsyncSession, state: FSMContext) -> None:
        if not await _require_owner(session, message.from_user.id):
            return  # oddiy foydalanuvchiga bu buyruq umuman ko'rinmasligi kerak
        await state.clear()
        await state.set_state(BroadcastStates.waiting_for_content)
        await message.answer(
            "📬 Barcha foydalanuvchilaringizga yuboriladigan xabarni yuboring "
            "(matn, rasm yoki video — izoh bilan).\n\n"
            "Bekor qilish uchun /bekor."
        )

    @router.message(BroadcastStates.waiting_for_content, Command("bekor"))
    async def on_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Bekor qilindi.")

    @router.message(BroadcastStates.waiting_for_content)
    async def on_content_received(message: Message, session: AsyncSession, state: FSMContext) -> None:
        if not await _require_owner(session, message.from_user.id):
            await state.clear()
            return

        result = await session.execute(
            select(func.count()).select_from(BotUser).where(BotUser.bot_id == bot_row.id)
        )
        user_count = result.scalar_one()

        await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
        await state.set_state(BroadcastStates.waiting_for_confirm)
        await message.answer(
            f"Bu xabar {user_count} ta foydalanuvchiga yuboriladi. Tasdiqlaysizmi?",
            reply_markup=_confirm_keyboard(),
        )

    @router.callback_query(BroadcastStates.waiting_for_confirm, F.data == "broadcast_cancel")
    async def on_confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.message.edit_text("Bekor qilindi.")
        await callback.answer()

    @router.callback_query(BroadcastStates.waiting_for_confirm, F.data == "broadcast_confirm")
    async def on_confirm(
        callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: AiogramBot
    ) -> None:
        if not await _require_owner(session, callback.from_user.id):
            await callback.answer()
            return

        try:
            await check_and_increment_feature_limit(
                session, bot_row.id, BROADCAST_FEATURE_KEY, BROADCAST_DAILY_LIMIT
            )
        except LimitExceededError as exc:
            await callback.answer(f"Kunlik limit: {exc}", show_alert=True)
            await state.clear()
            return

        data = await state.get_data()
        from_chat_id = data.get("from_chat_id")
        message_id = data.get("message_id")
        await state.clear()

        await callback.message.edit_text("⏳ Yuborilmoqda... Yakunlangach xabar beraman.")
        await callback.answer()

        # Fon vazifasi sifatida — webhook javobini bloklamaydi, uzoq
        # ro'yxatlarda ham darhol javob qaytadi.
        asyncio.create_task(
            _run_broadcast(bot, bot_row.id, callback.from_user.id, from_chat_id, message_id)
        )

    dp.include_router(router)
