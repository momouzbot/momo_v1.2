"""
Momo bot — asosiy boshqaruv boti (TZ 5-bo'lim + 8-bo'lim: Momo Admin roli).

Oddiy mijoz uchun:
    /start, /newbot -> token yuborish -> modul tanlash -> bot avtomatik tayyor
    /mybots -> mijozning botlari ro'yxati

Momo Admin uchun (faqat is_momo_admin=True bo'lganlar ko'radi):
    /admin -> barcha modullar ro'yxati, har birini yoqish/o'chirish tugmasi
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
from app.services.modules import list_modules, set_module_active
from app.services.registration import AlreadyRegisteredError, register_bot_for_owner
from app.services.telegram import InvalidTokenError
from app.services.users import get_or_create_user

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


def _admin_modules_keyboard(modules: list[Module]):
    builder = InlineKeyboardBuilder()
    for module in modules:
        status_icon = "✅" if module.is_active else "❌"
        label = _MODULE_LABELS.get(module.code, module.name)
        builder.button(text=f"{status_icon} {label}", callback_data=f"admin_toggle:{module.code.value}")
    builder.adjust(1)
    return builder.as_markup()


def build_momo_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.update.middleware(DBSessionMiddleware())

    router = Router(name="momo_main")

    # -----------------------------------------------------------------
    # Oddiy mijoz oqimi
    # -----------------------------------------------------------------

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await state.clear()
        # get_or_create_user shu yerda chaqiriladi — shu bilan birga
        # super_admin_telegram_id mos kelsa, avtomatik admin qilib belgilaydi.
        await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        await session.commit()

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
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

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

    # -----------------------------------------------------------------
    # Momo Admin oqimi (TZ 8-bo'lim) — MUHIM: bu handler "token kutish"
    # holati handleridan (on_token_received) OLDIN ro'yxatdan o'tishi
    # SHART. Aks holda, agar foydalanuvchi /newbot bosib "token kutish"
    # holatida bo'lsa, keyin /admin yuborsa — aiogram handlerlarni
    # ro'yxatdan o'tish tartibida tekshiradi va on_token_received uni
    # (Command filtersiz, faqat State filtri bilan) "noto'g'ri token"
    # deb qabul qilib oladi, /admin hech qachon ishlamay qoladi.
    # -----------------------------------------------------------------

    @router.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await state.clear()  # /admin buyrug'i "token kutish" kabi holatlarni bekor qiladi
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

        if not user.is_momo_admin:
            await message.answer("Bu buyruq faqat Momo Admin uchun.")
            return

        modules = await list_modules(session)
        if not modules:
            await message.answer("Modullar ro'yxati bo'sh (seed ishga tushmagan bo'lishi mumkin).")
            return

        await message.answer(
            "Modullarni boshqarish. Bosilgan modul yoqiladi/o'chiriladi:\n"
            "(✅ = yoqilgan, foydalanuvchilarga ko'rinadi, ❌ = o'chirilgan)",
            reply_markup=_admin_modules_keyboard(modules),
        )

    @router.message(RegisterStates.waiting_for_token, F.text.startswith("/"))
    async def on_command_while_waiting_token(message: Message, state: FSMContext) -> None:
        """
        Himoya qatlami: agar "token kutish" holatida foydalanuvchi biror
        buyruq (/admin, /mybots va h.k.) yuborsa — buni token sifatida
        qabul qilmaymiz, holatni bekor qilib, umumiy fallback orqali
        yo'naltiramiz (yoki yuqoridagi tegishli Command handler allaqachon
        ushlagan bo'ladi, chunki bu handler ulardan KEYIN ro'yxatdan o'tgan).
        """
        await state.clear()
        await message.answer(
            "Buyruqni bekor qildim (token kutish rejimidan chiqdingiz). "
            "Qaytadan bot yaratish uchun /newbot yuboring."
        )

    @router.message(RegisterStates.waiting_for_token)
    async def on_token_received(message: Message, state: FSMContext, session: AsyncSession) -> None:
        token = (message.text or "").strip()
        if ":" not in token or len(token) < 20:
            await message.answer(
                "Bu to'g'ri token ko'rinishida emas. "
                "BotFather'dan olingan tokenni to'liq nusxalab yuboring (masalan: 123456:AAExample...)."
            )
            return

        await state.update_data(bot_token=token)

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

    # -----------------------------------------------------------------
    # Momo Admin: modul yoqish/o'chirish tugmasi (callback)
    # -----------------------------------------------------------------

    @router.callback_query(F.data.startswith("admin_toggle:"))
    async def on_admin_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
        user = await get_or_create_user(session, telegram_id=callback.from_user.id)
        await session.commit()

        if not user.is_momo_admin:
            await callback.answer("Bu amal faqat Momo Admin uchun.", show_alert=True)
            return

        module_value = callback.data.split(":", 1)[1]
        module_type = ModuleType(module_value)

        modules = await list_modules(session)
        current = next((m for m in modules if m.code == module_type), None)
        if current is None:
            await callback.answer("Modul topilmadi.", show_alert=True)
            return

        updated = await set_module_active(session, module_type, not current.is_active)
        modules = await list_modules(session)

        state_text = "yoqildi" if updated.is_active else "o'chirildi"
        await callback.answer(f"{_MODULE_LABELS.get(module_type, module_type.value)} {state_text}.")
        await callback.message.edit_reply_markup(reply_markup=_admin_modules_keyboard(modules))

    # -----------------------------------------------------------------

    @router.message()
    async def fallback(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state is None:
            await message.answer(
                "Yangi bot yaratish uchun /newbot, botlaringizni ko'rish uchun /mybots yuboring."
            )

    dp.include_router(router)
    return dp
