"""
Momo bot — asosiy boshqaruv boti (TZ 5-bo'lim + 8-bo'lim: Momo Admin roli).

Oddiy mijoz uchun:
    /start -> (agar birinchi marta bo'lsa) qisqa ro'yxatdan o'tish:
              ism -> telefon -> ta'rif tanlash -> asosiy menyu (doimiy tugmali)
    Asosiy menyu: "🤖 Botlarim", "➕ Yangi bot", "👤 Profil", "🆘 Yordam"
    /newbot -> token yuborish -> modul tanlash -> bot avtomatik tayyor
    /mybots -> mijozning botlari ro'yxati

Momo Admin uchun (faqat is_momo_admin=True bo'lganlar ko'radi):
    /admin -> barcha modullar ro'yxati, har birini yoqish/o'chirish tugmasi
    (asosiy menyuda qo'shimcha "⚙️ Admin panel" tugmasi ko'rinadi)
"""
from __future__ import annotations

import logging
import re

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dispatcher.middleware import DBSessionMiddleware
from app.models.base import ModuleType, TariffCode
from app.models.bot import Bot as BotModel
from app.models.module import Module
from app.models.tariff import Tariff
from app.services.limits import LimitExceededError, get_tariff_by_code
from app.services.modules import list_modules, set_module_active
from app.services.registration import AlreadyRegisteredError, register_bot_for_owner
from app.services.telegram import InvalidTokenError
from app.services.users import complete_registration, get_or_create_user

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

# --- Asosiy menyu tugmalari matni (reply-keyboard) ---
MENU_MY_BOTS = "🤖 Botlarim"
MENU_NEW_BOT = "➕ Yangi bot"
MENU_PROFILE = "👤 Profil"
MENU_HELP = "🆘 Yordam"
MENU_ADMIN = "⚙️ Admin panel"

_RESERVED_MENU_TEXTS = {MENU_MY_BOTS, MENU_NEW_BOT, MENU_PROFILE, MENU_HELP, MENU_ADMIN}

_PHONE_RE = re.compile(r"^\+?\d{9,15}$")


class RegisterStates(StatesGroup):
    """Qisqa ro'yxatdan o'tish oqimi: ism -> telefon -> ta'rif (TZ 5-bo'lim)."""

    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_tariff = State()


class NewBotStates(StatesGroup):
    """Yangi mijoz-bot yaratish oqimi (token -> modul tanlash)."""

    waiting_for_token = State()
    waiting_for_module = State()


class AdminStates(StatesGroup):
    waiting_for_pin = State()


# -----------------------------------------------------------------
# Klaviatura yordamchilari
# -----------------------------------------------------------------


def _main_menu_keyboard(is_momo_admin: bool) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text=MENU_MY_BOTS), KeyboardButton(text=MENU_NEW_BOT))
    builder.row(KeyboardButton(text=MENU_PROFILE), KeyboardButton(text=MENU_HELP))
    if is_momo_admin:
        builder.row(KeyboardButton(text=MENU_ADMIN))
    return builder.as_markup(resize_keyboard=True)


def _phone_request_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📞 Raqamni yuborish", request_contact=True))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def _admin_modules_keyboard(modules: list[Module]):
    builder = InlineKeyboardBuilder()
    for module in modules:
        status_icon = "✅" if module.is_active else "❌"
        label = _MODULE_LABELS.get(module.code, module.name)
        builder.button(text=f"{status_icon} {label}", callback_data=f"admin_toggle:{module.code.value}")
    builder.adjust(1)
    return builder.as_markup()


def _format_tariff_detail(t: Tariff) -> str:
    lines = [f"📦 {t.name} tarifi"]
    if t.description:
        lines.append(t.description)
    lines.append(f"• Bot soni: {t.bot_limit} ta")
    lines.append(f"• Kunlik tahrir limiti: {t.edit_limit_per_day} marta")
    lines.append(f"• Muddat: {t.duration_days} kun" if t.duration_days else "• Muddat: muddatsiz")
    if float(t.upgrade_price) > 0:
        lines.append(f"• Tarifga o'tish narxi: {int(t.upgrade_price)} so'm")
    lines.append(
        f"• Hosting narxi (oyiga, {t.user_threshold} foydalanuvchigacha): {int(t.base_hosting_price)} so'm"
    )
    return "\n".join(lines)


def _tariff_list_keyboard(tariffs: list[Tariff]):
    builder = InlineKeyboardBuilder()
    for t in tariffs:
        if t.code == TariffCode.START:
            hint = "bepul"
        else:
            hint = f"{int(t.base_hosting_price)} so'm/oy dan"
        builder.button(text=f"{t.name} — {hint}", callback_data=f"tariff_view:{t.code.value}")
    builder.adjust(1)
    return builder.as_markup()


async def _get_all_tariffs(session: AsyncSession) -> list[Tariff]:
    result = await session.execute(select(Tariff).order_by(Tariff.bot_limit))
    return list(result.scalars().all())


def build_momo_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.update.middleware(DBSessionMiddleware())

    router = Router(name="momo_main")

    # -----------------------------------------------------------------
    # /start va ro'yxatdan o'tish oqimi (ism -> telefon -> ta'rif)
    # -----------------------------------------------------------------

    @router.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await state.clear()
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        await session.commit()

        if user.registration_completed:
            await message.answer(
                f"Xush kelibsiz, {user.full_name}!\n\n"
                "Quyidagi menyudan foydalaning.",
                reply_markup=_main_menu_keyboard(user.is_momo_admin),
            )
            return

        await message.answer(
            "Assalomu alaykum! Men Momo, siz uchun Telegram-bot yarataman.\n\n"
            "Boshlashdan oldin qisqa ro'yxatdan o'taylik (atigi 3 qadam).\n\n"
            "1/3. Ismingizni kiriting:",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(RegisterStates.waiting_for_name)

    @router.message(RegisterStates.waiting_for_name)
    async def on_name_received(message: Message, state: FSMContext) -> None:
        name = (message.text or "").strip()
        if not name or name.startswith("/"):
            await message.answer("Iltimos, ismingizni oddiy matn ko'rinishida kiriting:")
            return

        await state.update_data(full_name=name)
        await message.answer(
            f"Rahmat, {name}!\n\n"
            "2/3. Endi telefon raqamingizni yuboring — pastdagi tugmani bosing "
            "yoki qo'lda kiriting (masalan: +998901234567):",
            reply_markup=_phone_request_keyboard(),
        )
        await state.set_state(RegisterStates.waiting_for_phone)

    async def _proceed_to_tariff_selection(
        message: Message, state: FSMContext, session: AsyncSession, phone: str
    ) -> None:
        await state.update_data(phone_number=phone)

        tariffs = await _get_all_tariffs(session)
        if not tariffs:
            await message.answer(
                "Ta'riflar hozircha yuklanmagan. Birozdan keyin qaytadan urinib ko'ring: /start",
                reply_markup=ReplyKeyboardRemove(),
            )
            await state.clear()
            return

        await message.answer("Telefon raqami qabul qilindi.", reply_markup=ReplyKeyboardRemove())
        await message.answer(
            "3/3. Endi ta'rif turini tanlang. Har birini bosganda batafsil ma'lumot (narx, "
            "limit, muddat) ko'rasiz:",
            reply_markup=_tariff_list_keyboard(tariffs),
        )
        await state.set_state(RegisterStates.waiting_for_tariff)

    @router.message(RegisterStates.waiting_for_phone, F.contact)
    async def on_phone_contact(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _proceed_to_tariff_selection(message, state, session, message.contact.phone_number)

    @router.message(RegisterStates.waiting_for_phone)
    async def on_phone_text(message: Message, state: FSMContext, session: AsyncSession) -> None:
        phone = (message.text or "").strip()
        if not _PHONE_RE.match(phone):
            await message.answer(
                "Telefon raqami noto'g'ri ko'rinishda. Masalan: +998901234567.\n"
                "Qaytadan kiriting yoki pastdagi tugmani bosing:"
            )
            return
        await _proceed_to_tariff_selection(message, state, session, phone)

    @router.callback_query(RegisterStates.waiting_for_tariff, F.data.startswith("tariff_view:"))
    async def on_tariff_view(callback: CallbackQuery, session: AsyncSession) -> None:
        code = TariffCode(callback.data.split(":", 1)[1])
        tariff = await get_tariff_by_code(session, code)

        kb = InlineKeyboardBuilder()
        kb.button(text=f"✅ {tariff.name} tarifini tanlash", callback_data=f"tariff_pick:{code.value}")
        kb.button(text="⬅️ Orqaga", callback_data="tariff_back")
        kb.adjust(1)

        await callback.message.edit_text(_format_tariff_detail(tariff), reply_markup=kb.as_markup())
        await callback.answer()

    @router.callback_query(RegisterStates.waiting_for_tariff, F.data == "tariff_back")
    async def on_tariff_back(callback: CallbackQuery, session: AsyncSession) -> None:
        tariffs = await _get_all_tariffs(session)
        await callback.message.edit_text(
            "Ta'rif turini tanlang. Har birini bosganda batafsil ma'lumot ko'rasiz:",
            reply_markup=_tariff_list_keyboard(tariffs),
        )
        await callback.answer()

    @router.callback_query(RegisterStates.waiting_for_tariff, F.data.startswith("tariff_pick:"))
    async def on_tariff_pick(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        code = TariffCode(callback.data.split(":", 1)[1])
        tariff = await get_tariff_by_code(session, code)

        data = await state.get_data()
        full_name = data.get("full_name") or callback.from_user.full_name
        phone_number = data.get("phone_number") or ""

        user = await complete_registration(
            session,
            telegram_id=callback.from_user.id,
            full_name=full_name,
            phone_number=phone_number,
            preferred_tariff_code=code,
        )
        await session.commit()
        await state.clear()

        note = ""
        if code != TariffCode.START:
            note = (
                "\n\nBu — pullik tarif. Yangi botingiz hozircha bepul Start tarifida ishga "
                "tushadi; tanlagan tarifingizni faollashtirish uchun keyinroq to'lov qilib, "
                "admin tomonidan tasdiqlatasiz."
            )

        await callback.message.edit_text(
            f"✅ Ro'yxatdan o'tish yakunlandi!\nTanlangan tarif: {tariff.name}.{note}"
        )
        await callback.answer("Ro'yxatdan o'tish yakunlandi!")
        await callback.message.answer(
            "Endi botingizni yaratishingiz mumkin. Quyidagi menyudan foydalaning:",
            reply_markup=_main_menu_keyboard(user.is_momo_admin),
        )

    # -----------------------------------------------------------------
    # Asosiy menyu: Botlarim / Yangi bot / Profil / Yordam
    # -----------------------------------------------------------------

    async def _show_my_bots(message: Message, session: AsyncSession) -> None:
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

        result = await session.execute(select(BotModel).where(BotModel.owner_id == user.id))
        bots = result.scalars().all()

        if not bots:
            await message.answer(f"Sizda hali botlar yo'q. Yaratish uchun \"{MENU_NEW_BOT}\" tugmasini bosing.")
            return

        status_emoji = {"active": "OK", "paused": "PAUSED", "suspended": "SUSPENDED", "deleted": "DELETED"}
        lines = ["Sizning botlaringiz:\n"]
        for b in bots:
            emoji = status_emoji.get(b.status.value, "?")
            label = _MODULE_LABELS.get(b.module_type, b.module_type.value)
            lines.append(f"[{emoji}] @{b.username} - {label}")
        await message.answer("\n".join(lines))

    @router.message(Command("mybots"))
    async def cmd_mybots(message: Message, session: AsyncSession) -> None:
        await _show_my_bots(message, session)

    @router.message(F.text == MENU_MY_BOTS)
    async def on_menu_my_bots(message: Message, session: AsyncSession) -> None:
        await _show_my_bots(message, session)

    async def _start_new_bot_flow(message: Message, state: FSMContext, session: AsyncSession) -> None:
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

        if not user.registration_completed:
            await message.answer("Avval qisqa ro'yxatdan o'ting: /start")
            return

        await state.set_state(NewBotStates.waiting_for_token)
        await message.answer("Bot tokenini yuboring (BotFather'dan olingan):")

    @router.message(Command("newbot"))
    async def cmd_newbot(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _start_new_bot_flow(message, state, session)

    @router.message(F.text == MENU_NEW_BOT)
    async def on_menu_new_bot(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _start_new_bot_flow(message, state, session)

    @router.message(F.text == MENU_PROFILE)
    async def on_menu_profile(message: Message, session: AsyncSession) -> None:
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

        lines = [
            "👤 Profilingiz",
            f"Ism: {user.full_name or '—'}",
            f"Telefon: {user.phone_number or '—'}",
        ]
        if user.preferred_tariff_code:
            tariff = await get_tariff_by_code(session, user.preferred_tariff_code)
            lines.append(f"Tanlagan ta'rif: {tariff.name}")
        await message.answer("\n".join(lines))

    @router.message(F.text == MENU_HELP)
    async def on_menu_help(message: Message) -> None:
        await message.answer(
            "🆘 Yordam\n\n"
            f"{MENU_MY_BOTS} — botlaringiz ro'yxati va holati\n"
            f"{MENU_NEW_BOT} — yangi bot yaratish\n"
            f"{MENU_PROFILE} — shaxsiy ma'lumotlaringiz\n\n"
            "Savolingiz bo'lsa, Momo Admin bilan bog'laning."
        )

    # -----------------------------------------------------------------
    # Momo Admin oqimi (TZ 8-bo'lim) — MUHIM: bu handlerlar "token kutish"
    # holati handleridan (on_token_received) OLDIN ro'yxatdan o'tishi
    # SHART, aks holda navbat tartibi buziladi (aiogram handlerlarni
    # ro'yxatdan o'tish tartibida tekshiradi).
    # -----------------------------------------------------------------

    async def _send_admin_panel(message: Message, session: AsyncSession) -> None:
        modules = await list_modules(session)
        if not modules:
            await message.answer("Modullar ro'yxati bo'sh (seed ishga tushmagan bo'lishi mumkin).")
            return

        await message.answer(
            "Modullarni boshqarish. Bosilgan modul yoqiladi/o'chiriladi:\n"
            "(✅ = yoqilgan, foydalanuvchilarga ko'rinadi, ❌ = o'chirilgan)",
            reply_markup=_admin_modules_keyboard(modules),
        )

    async def _open_admin_panel(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await state.clear()  # /admin buyrug'i "token kutish" kabi holatlarni bekor qiladi
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

        if not user.is_momo_admin:
            # Momo Admin bo'lmagan foydalanuvchiga PIN so'ralganini ham bildirmaymiz —
            # aks holda bu buyruq admin panelining mavjudligini oshkor qiladi.
            await message.answer("Bu buyruq faqat Momo Admin uchun.")
            return

        if not settings.admin_pin:
            logger.warning("ADMIN_PIN sozlanmagan — /admin paneli PIN'siz ochildi.")
            await _send_admin_panel(message, session)
            return

        await state.set_state(AdminStates.waiting_for_pin)
        await message.answer("🔐 Xavfsizlik uchun admin PIN kodini kiriting:")

    @router.message(Command("admin"))
    async def cmd_admin(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _open_admin_panel(message, state, session)

    @router.message(F.text == MENU_ADMIN)
    async def on_menu_admin(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _open_admin_panel(message, state, session)

    @router.message(AdminStates.waiting_for_pin, F.text.startswith("/") | F.text.in_(_RESERVED_MENU_TEXTS))
    async def on_command_while_waiting_pin(message: Message, state: FSMContext) -> None:
        """PIN kutish holatida boshqa buyruq/menyu tugmasi bosilsa — buni PIN sifatida qabul qilmaymiz."""
        await state.clear()
        await message.answer("PIN kiritish bekor qilindi. Qaytadan ochish uchun /admin yuboring.")

    @router.message(AdminStates.waiting_for_pin)
    async def on_admin_pin_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await state.clear()

        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

        entered_pin = (message.text or "").strip()
        if not user.is_momo_admin or entered_pin != settings.admin_pin:
            # Xato PIN yoki holat davomida admin huquqi yo'qolgan bo'lsa —
            # aniq sabab aytilmaydi (brute-force/enumeration'ga qarshi).
            await message.answer("Noto'g'ri PIN. Qaytadan urinish uchun /admin yuboring.")
            return

        await _send_admin_panel(message, session)

    @router.message(NewBotStates.waiting_for_token, F.text.startswith("/") | F.text.in_(_RESERVED_MENU_TEXTS))
    async def on_command_while_waiting_token(message: Message, state: FSMContext) -> None:
        """
        Himoya qatlami: agar "token kutish" holatida foydalanuvchi biror
        buyruq yoki menyu tugmasini bossa — buni token sifatida qabul
        qilmaymiz, holatni bekor qilamiz.
        """
        await state.clear()
        await message.answer(
            "Buyruqni bekor qildim (token kutish rejimidan chiqdingiz). "
            f"Qaytadan bot yaratish uchun \"{MENU_NEW_BOT}\" tugmasini bosing yoki /newbot yuboring."
        )

    @router.message(NewBotStates.waiting_for_token)
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
        await state.set_state(NewBotStates.waiting_for_module)

    @router.callback_query(NewBotStates.waiting_for_module, F.data.startswith("reg_module:"))
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
    async def fallback(message: Message, state: FSMContext, session: AsyncSession) -> None:
        current_state = await state.get_state()
        if current_state is not None:
            return
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()
        if not user.registration_completed:
            await message.answer("Ro'yxatdan o'tish uchun /start yuboring.")
            return
        await message.answer(
            "Quyidagi menyudan foydalaning yoki yangi bot yaratish uchun "
            f"\"{MENU_NEW_BOT}\" tugmasini bosing.",
            reply_markup=_main_menu_keyboard(user.is_momo_admin),
        )

    dp.include_router(router)
    return dp
