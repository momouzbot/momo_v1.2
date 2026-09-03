"""
Momo bot — asosiy boshqaruv boti (TZ 5-bo'lim).

Bu — mijozlar bevosita Telegram orqali gaplashadigan yagona bot. Oqim:
    /start -> yo'riqnoma
    mijoz bot tokenini yuboradi -> validatsiya
    modul turini tanlaydi (faqat is_active=True bo'lganlar ko'rsatiladi) -> tugma
    -> avtomatik ro'yxatdan o'tkaziladi, webhook o'rnatiladi, natija xabar qilinadi

Bu HTTP API'dan (`/api/registration/register`) farqli — mijoz uchun asosiy,
kutilgan tajriba shu: token yubordi, tugmani bosdi, boti tayyor.
"""
from __future__ import annotations

import logging

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatcher.middleware import DBSessionMiddleware
from app.models.base import ModuleType
from app.models.bot import Bot as BotModel
from app.models.module import Module
from app.services.limits import LimitExceededError
from app.services.registration import AlreadyRegisteredError, register_bot_for_owner
from app.services.telegram import InvalidTokenError

logger = logging.getLogger(__name__)

_MODULE_LABELS = {
    ModuleType.ADMIN: "Admin-bot",
    ModuleType.SUPPORT: "Murojaat-bot",
    ModuleType.KINO: "Kino-bot",
    ModuleType.SHOP: "Do'kon-bot",
    ModuleType.GAME_GOT: "GOT Game",
    ModuleType.GAME_MAFIA: "Mafia",
    ModuleType.GAME_BUNKER: "Bunker",
    ModuleType.CUSTOM: "Custom-bot",
}


class RegisterStates(StatesGroup):
    waiting_for_token = State()
    waiting_for_module = State()


def build_momo_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.update.middleware(DBSessionMiddleware())

    router = Router(name="momo_main")

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(
            "Assalomu alaykum! Men Momo, siz uchun Telegram-bot yarataman.\n\n"
            "Yangi bot yaratish uchun:\n"
            "1) BotFather orqali yangi bot yarating va tokenini oling\n"
            "2) Shu yerga o'sha tokenni yuboring\n"
            "3) Bot turini tanlang - qolganini o'zim qilaman.\n\n"
            "Botlaringiz ro'yxatini ko'rish uchun /mybots yuboring."
        )
        await state.set_state(RegisterStates.waiting_for_token)

    @router.message(Command("newbot"))
    async def cmd_newbot(message: Message, state: FSMContext) -> None:
        await state.set_state(RegisterStates.waiting_for_token)
        await message.answer("Bot tokenini yuboring (BotFather'dan olingan):")

    @router.message(Command("mybots"))
    async def cmd_mybots(message: Message, session: AsyncSession) -> None:
        from app.services.users import get_or_create_user

        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        result = await session.execute(select(BotModel).where(BotModel.owner_id == user.id))
        bots = result.scalars().all()

        if not bots:
            await message.answer("Sizda hali botlar yo'q. Yaratish uchun /newbot yuboring.")
            return

        status_emoji = {"active": "OK", "paused": "PAUSED", "suspended": "SUSPENDED", "deleted": "DELETED"}
        lines = ["Sizning botlaringiz:\n"]
        for b in bots:
            emoji = status_emoji.get(b.status.value, "?")
            label = _MODULE_LABELS.get(b.module_type, b.module_type.value)
            lines.append(f"[{emoji}] @{b.username} - {label}")
        await message.answer("\n".join(lines))

    @router.message(RegisterStates.waiting_for_token)
    async def on_token_received(message: Message, state: FSMContext) -> None:
        token = (message.text or "").strip()
        if ":" not in token or len(token) < 20:
            await message.answer(
                "Bu to'g'ri token ko'rinishida emas. "
                "BotFather'dan olingan tokenni to'liq nusxalab yuboring (masalan: 123456:AAExample...)."
            )
            return

        await state.update_data(bot_token=token)

        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Module).where(Module.is_active.is_(True)).order_by(Module.code)
            )
            active_modules = result.scalars().all()

        if not active_modules:
            await message.answer("Hozircha mavjud modullar yo'q. Birozdan keyin urinib ko'ring.")
            await state.clear()
            return

        builder = InlineKeyboardBuilder()
        for module in active_modules:
            label = _MODULE_LABELS.get(module.code, module.name)
            builder.button(text=label, callback_data=f"reg_module:{module.code.value}")
        builder.adjust(1)

        await message.answer("Token qabul qilindi. Endi bot turini tanlang:", reply_markup=builder.as_markup())
        await state.set_state(RegisterStates.waiting_for_module)

    @router.callback_query(RegisterStates.waiting_for_module, F.data.startswith("reg_module:"))
    async def on_module_selected(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        module_value = callback.data.split(":", 1)[1]
        module_type = ModuleType(module_value)

        data = await state.get_data()
        bot_token = data.get("bot_token")

        await callback.message.edit_text("Bot yaratilmoqda, biroz kuting...")
        await callback.answer()

        try:
            bot_row, _ = await register_bot_for_owner(
                session,
                owner_telegram_id=callback.from_user.id,
                owner_username=callback.from_user.username,
                owner_full_name=callback.from_user.full_name,
                bot_token=bot_token,
                module_type=module_type,
                externally_hosted=False,
            )
        except InvalidTokenError:
            await callback.message.answer("Token noto'g'ri yoki eskirgan. Qaytadan urinib ko'ring: /newbot")
            await state.clear()
            return
        except AlreadyRegisteredError:
            await callback.message.answer("Bu bot allaqachon ro'yxatdan o'tgan. Boshqa token yuboring: /newbot")
            await state.clear()
            return
        except LimitExceededError as exc:
            await callback.message.answer(
                f"Bot limitiga yetdingiz ({exc}). Tarifni oshirish uchun admin bilan bog'laning."
            )
            await state.clear()
            return
        except Exception:
            logger.exception("Bot ro'yxatdan o'tkazishda kutilmagan xato")
            await callback.message.answer("Kutilmagan xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.")
            await state.clear()
            return

        webhook_note = "Webhook o'rnatildi." if bot_row.webhook_set else "Webhook o'rnatilmadi (qayta urinib ko'ring)."
        label = _MODULE_LABELS.get(module_type, module_type.value)
        await callback.message.answer(
            f"Bot tayyor!\n\n"
            f"Bot: @{bot_row.username}\n"
            f"Turi: {label}\n"
            f"Tarif: Start (bepul)\n"
            f"{webhook_note}\n\n"
            f"Endi @{bot_row.username} ga o'tib /start bosing!"
        )
        await state.clear()

    @router.message()
    async def fallback(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state is None:
            await message.answer("Yangi bot yaratish uchun /newbot, botlaringizni ko'rish uchun /mybots yuboring.")

    dp.include_router(router)
    return dp
