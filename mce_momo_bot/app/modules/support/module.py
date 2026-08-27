"""
MurojaatModule (`support`) — TZ 4.2-bo'lim, to'liq DB bilan bog'langan versiya.

Oqim:
    /start -> xush kelibsiz + yo'riqnoma
    /murojaat -> kategoriya tanlash (inline tugmalar)
    kategoriya tanlangach -> foydalanuvchi matn yozadi -> Appeal yaratiladi
                             -> admin_chat_id ga forward qilinadi
    /tarix -> foydalanuvchining oldingi murojaatlari ro'yxati (oxirgi 5 tasi)

Admin guruhida forward qilingan xabarga reply qilinsa (adminlar tomonidan),
javob avtomatik ravishda foydalanuvchiga yuboriladi (reply-orqali-javob mexanizmi).
"""
from __future__ import annotations

import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appeal import Appeal, AppealCategory, AppealStatus
from app.modules.base import BaseModule

logger = logging.getLogger(__name__)

_CATEGORY_LABELS = {
    AppealCategory.TECHNICAL: "🛠 Texnik",
    AppealCategory.FINANCIAL: "💰 Moliyaviy",
    AppealCategory.GENERAL: "💬 Umumiy",
}


class SupportStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_message = State()


class SupportModule(BaseModule):
    def register_handlers(self, dp: Dispatcher) -> None:
        router = Router(name=f"support_{self.bot_row.id}")
        bot_row = self.bot_row  # closure ichida ishlatish uchun

        @router.message(CommandStart())
        async def cmd_start(message: Message) -> None:
            await message.answer(
                "Assalomu alaykum! Bu — murojaatlar bo'limi.\n\n"
                "📝 Yangi murojaat qoldirish uchun /murojaat\n"
                "📋 Oldingi murojaatlaringizni ko'rish uchun /tarix"
            )

        @router.message(F.text == "/murojaat")
        async def cmd_new_appeal(message: Message, state: FSMContext) -> None:
            builder = InlineKeyboardBuilder()
            for category, label in _CATEGORY_LABELS.items():
                builder.button(text=label, callback_data=f"appeal_cat:{category.value}")
            builder.adjust(1)
            await message.answer("Murojaat kategoriyasini tanlang:", reply_markup=builder.as_markup())
            await state.set_state(SupportStates.waiting_for_category)

        @router.callback_query(F.data.startswith("appeal_cat:"))
        async def on_category_chosen(callback: CallbackQuery, state: FSMContext) -> None:
            category_value = callback.data.split(":", 1)[1]
            await state.update_data(category=category_value)
            await state.set_state(SupportStates.waiting_for_message)
            await callback.message.edit_text(
                f"Kategoriya: {_CATEGORY_LABELS[AppealCategory(category_value)]}\n\n"
                "Endi murojaat matnini yozing:"
            )
            await callback.answer()

        @router.message(SupportStates.waiting_for_message)
        async def on_appeal_text(message: Message, state: FSMContext, session: AsyncSession, bot: AiogramBot) -> None:
            data = await state.get_data()
            category = AppealCategory(data.get("category", AppealCategory.GENERAL.value))

            appeal = Appeal(
                bot_id=bot_row.id,
                telegram_user_id=message.from_user.id,
                category=category,
                status=AppealStatus.NEW,
                message_text=message.text or "",
            )
            session.add(appeal)
            await session.flush()

            if bot_row.admin_chat_id:
                try:
                    forwarded = await bot.send_message(
                        chat_id=bot_row.admin_chat_id,
                        text=(
                            f"🆕 Murojaat #{appeal.id}\n"
                            f"Kategoriya: {_CATEGORY_LABELS[category]}\n"
                            f"Foydalanuvchi: {message.from_user.full_name} "
                            f"(id: {message.from_user.id})\n\n"
                            f"{appeal.message_text}\n\n"
                            f"↩️ Javob berish uchun shu xabarga reply qiling."
                        ),
                    )
                    appeal.forwarded_message_id = forwarded.message_id
                except Exception:
                    logger.exception("Murojaatni admin guruhga forward qilishda xato: appeal_id=%s", appeal.id)
            else:
                logger.warning("admin_chat_id sozlanmagan: bot_id=%s — murojaat forward qilinmadi", bot_row.id)

            await session.commit()
            await state.clear()
            await message.answer("✅ Murojaatingiz qabul qilindi. Tez orada javob beramiz.")

        @router.message(F.text == "/tarix")
        async def cmd_history(message: Message, session: AsyncSession) -> None:
            result = await session.execute(
                select(Appeal)
                .where(Appeal.bot_id == bot_row.id, Appeal.telegram_user_id == message.from_user.id)
                .order_by(Appeal.created_at.desc())
                .limit(5)
            )
            appeals = result.scalars().all()

            if not appeals:
                await message.answer("Sizda hali murojaatlar yo'q.")
                return

            status_labels = {
                AppealStatus.NEW: "🆕 Yangi",
                AppealStatus.IN_PROGRESS: "⏳ Ko'rib chiqilmoqda",
                AppealStatus.ANSWERED: "✅ Javob berilgan",
                AppealStatus.CLOSED: "🔒 Yopilgan",
            }
            lines = ["📋 Sizning so'nggi murojaatlaringiz:\n"]
            for appeal in appeals:
                preview = appeal.message_text[:60] + ("…" if len(appeal.message_text) > 60 else "")
                lines.append(f"#{appeal.id} [{status_labels[appeal.status]}] {preview}")
                if appeal.admin_reply_text:
                    lines.append(f"   ↳ Javob: {appeal.admin_reply_text[:100]}")

            await message.answer("\n".join(lines))

        # --- Admin guruhidan reply orqali javob berish ---
        @router.message(F.reply_to_message, F.chat.id == bot_row.admin_chat_id)
        async def on_admin_reply(message: Message, session: AsyncSession, bot: AiogramBot) -> None:
            replied_id = message.reply_to_message.message_id
            result = await session.execute(
                select(Appeal).where(
                    Appeal.bot_id == bot_row.id, Appeal.forwarded_message_id == replied_id
                )
            )
            appeal = result.scalar_one_or_none()
            if appeal is None:
                return  # bu reply murojaatga tegishli emas

            appeal.admin_reply_text = message.text or ""
            appeal.status = AppealStatus.ANSWERED
            await session.commit()

            try:
                await bot.send_message(
                    chat_id=appeal.telegram_user_id,
                    text=f"💬 Murojaatingizga (#{appeal.id}) javob keldi:\n\n{appeal.admin_reply_text}",
                )
            except Exception:
                logger.exception("Foydalanuvchiga javob yuborishda xato: appeal_id=%s", appeal.id)

            await message.reply("✅ Javob foydalanuvchiga yuborildi.")

        @router.message()
        async def fallback(message: Message) -> None:
            await message.answer("Buyruqni tushunmadim. /murojaat yoki /tarix dan foydalaning.")

        # Core funksiyalar (captcha/welcome) avval ro'yxatdan o'tadi — aks holda
        # quyidagi modul routeridagi umumiy fallback handler ularni "yutib qo'yadi".
        self.register_core_features(dp)
        dp.include_router(router)
