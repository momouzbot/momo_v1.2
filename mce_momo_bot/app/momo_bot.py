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

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
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
from app.models.base import BotStatus, ModuleType, PaymentStatus, TariffCode
from app.models.bot import Bot as BotModel
from app.models.module import Module
from app.models.tariff import Tariff
from app.models.user import User
from app.services.limits import (
    LimitExceededError,
    calculate_hosting_price,
    get_active_bot_tariff,
    get_active_tariff,
    get_tariff_by_code,
    get_unique_user_count,
)
from app.services.modules import list_modules, set_module_active
from app.services.payments import (
    HostingPaymentAlreadyExistsError,
    hosting_payment_status_this_month,
    submit_hosting_payment,
    submit_tariff_upgrade,
)
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


class PaymentStates(StatesGroup):
    """"Botlarim" bo'limidan chek yuborish oqimi (TZ 5-bo'lim, batafsil holat)."""

    waiting_for_hosting_receipt = State()
    waiting_for_upgrade_tariff = State()   # tarif tanlanmoqda (inline ro'yxat ko'rsatilgan)
    waiting_for_upgrade_receipt = State()


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


_BOT_STATUS_ICON = {
    BotStatus.ACTIVE: "✅",
    BotStatus.PAUSED: "⏸",
    BotStatus.SUSPENDED: "⛔",
    BotStatus.DELETED: "🗑",
}

_BOT_STATUS_LABEL = {
    BotStatus.ACTIVE: "✅ Faol",
    BotStatus.PAUSED: "⏸ To'xtatilgan (hosting to'lanmagan)",
    BotStatus.SUSPENDED: "⛔ Muddat tugagan, Start'ga tushirilgan",
    BotStatus.DELETED: "🗑 O'chirilgan",
}

_HOSTING_PAYMENT_LABEL = {
    None: "❌ To'lanmagan",
    PaymentStatus.PENDING: "⏳ Kutilmoqda",
    PaymentStatus.APPROVED: "✅ To'langan",
    PaymentStatus.REJECTED: "❌ Rad etilgan (qayta yuboring)",
}


async def _get_owned_bot_or_none(session: AsyncSession, telegram_id: int, bot_id: int) -> BotModel | None:
    """Bot_id aynan shu telegram_id egasiga tegishli ekanini tekshiradi
    (boshqa mijozning botiga callback orqali kirib qolmaslik uchun)."""
    result = await session.execute(
        select(BotModel)
        .join(User, User.id == BotModel.owner_id)
        .where(BotModel.id == bot_id, User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def _my_bots_keyboard(session: AsyncSession, user: User) -> InlineKeyboardMarkup | None:
    result = await session.execute(select(BotModel).where(BotModel.owner_id == user.id))
    bots = result.scalars().all()
    if not bots:
        return None

    builder = InlineKeyboardBuilder()
    for b in bots:
        icon = _BOT_STATUS_ICON.get(b.status, "?")
        builder.button(text=f"{icon} @{b.username}", callback_data=f"bot_detail:{b.id}")
    builder.adjust(1)
    return builder.as_markup()


async def _format_bot_detail(session: AsyncSession, bot_row: BotModel) -> tuple[str, PaymentStatus | None]:
    """Bot uchun to'liq holat matnini qaytaradi: tarif, tugash sanasi, joriy oy
    foydalanuvchilari/narxi va to'lov holati — barchasi bazadan real vaqtda
    hisoblanadi (TZ 5-bo'lim, "Botlarim" batafsil karta)."""
    tariff = await get_active_tariff(session, bot_row.id)
    bot_tariff_row = await get_active_bot_tariff(session, bot_row.id)
    unique_users = await get_unique_user_count(session, bot_row.id)
    hosting_price = await calculate_hosting_price(session, bot_row.id, unique_users)
    payment_status = await hosting_payment_status_this_month(session, bot_row.id)

    expires_label = (
        bot_tariff_row.expires_at.strftime("%Y-%m-%d") if bot_tariff_row.expires_at else "Muddatsiz"
    )
    label = _MODULE_LABELS.get(bot_row.module_type, bot_row.module_type.value)
    status_label = _BOT_STATUS_LABEL.get(bot_row.status, bot_row.status.value)
    payment_label = _HOSTING_PAYMENT_LABEL[payment_status]

    lines = [
        f"🤖 @{bot_row.username}",
        f"Turi: {label}",
        f"Holat: {status_label}",
        "",
        f"📦 Tarif: {tariff.name}",
        f"📅 Tugash sanasi: {expires_label}",
        "",
        f"👥 Joriy oy foydalanuvchilari: {unique_users} ta",
        f"💰 Joriy oy hosting narxi: {int(hosting_price)} so'm",
        f"💳 Joriy oy to'lovi: {payment_label}",
    ]
    return "\n".join(lines), payment_status


def _bot_detail_keyboard(bot_id: int, payment_status: PaymentStatus | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if payment_status in (None, PaymentStatus.REJECTED):
        builder.button(text="💳 To'lov cheki yuborish", callback_data=f"pay_hosting:{bot_id}")
    builder.button(text="⬆️ Tarifni oshirish", callback_data=f"pay_upgrade:{bot_id}")
    builder.button(text="⬅️ Orqaga", callback_data="my_bots_back")
    builder.adjust(1)
    return builder.as_markup()


def _upgrade_tariff_keyboard(bot_id: int, other_tariffs: list[Tariff]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in other_tariffs:
        builder.button(text=f"{t.name} — {int(t.upgrade_price)} so'm", callback_data=f"upg_tariff_view:{t.code.value}")
    builder.button(text="⬅️ Orqaga", callback_data=f"bot_detail:{bot_id}")
    builder.adjust(1)
    return builder.as_markup()


async def _notify_admins_new_payment(
    session: AsyncSession, bot: AiogramBot, bot_id: int, kind_label: str, amount: float, receipt_file_id: str
) -> None:
    """Chek yuborilganda barcha Momo Adminlarga (is_momo_admin=True) chek
    screenshoti + qisqa ma'lumot yuboriladi (5-bosqichda botning o'zida
    tasdiqlash/rad etish qo'shilgach, shu yerdan to'g'ridan-to'g'ri amal
    qilinadigan bo'ladi)."""
    bot_result = await session.execute(select(BotModel).where(BotModel.id == bot_id))
    bot_row = bot_result.scalar_one_or_none()

    owner_label = "noma'lum"
    if bot_row is not None:
        owner_result = await session.execute(select(User).where(User.id == bot_row.owner_id))
        owner = owner_result.scalar_one_or_none()
        if owner is not None:
            owner_label = f"{owner.full_name or '—'} ({owner.phone_number or '—'})"

    admins_result = await session.execute(select(User).where(User.is_momo_admin.is_(True)))
    admins = admins_result.scalars().all()

    caption = (
        "🆕 Yangi to'lov cheki\n\n"
        f"Bot: @{bot_row.username if bot_row else bot_id}\n"
        f"Mijoz: {owner_label}\n"
        f"Turi: {kind_label}\n"
        f"Summa: {int(amount)} so'm"
    )
    for admin in admins:
        try:
            await bot.send_photo(admin.telegram_id, receipt_file_id, caption=caption)
        except Exception:
            logger.exception("Adminga to'lov haqida xabar yuborishda xato: admin_telegram_id=%s", admin.telegram_id)


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

    async def _show_my_bots(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await state.clear()  # botlar ro'yxatiga qaytish har qanday chek/tarif oqimini bekor qiladi
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

        kb = await _my_bots_keyboard(session, user)
        if kb is None:
            await message.answer(f"Sizda hali botlar yo'q. Yaratish uchun \"{MENU_NEW_BOT}\" tugmasini bosing.")
            return
        await message.answer("Sizning botlaringiz. Batafsil ma'lumot uchun bosing:", reply_markup=kb)

    @router.message(Command("mybots"))
    async def cmd_mybots(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _show_my_bots(message, state, session)

    @router.message(F.text == MENU_MY_BOTS)
    async def on_menu_my_bots(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _show_my_bots(message, state, session)

    @router.callback_query(F.data == "my_bots_back")
    async def on_my_bots_back(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        await state.clear()
        user = await get_or_create_user(session, telegram_id=callback.from_user.id)
        await session.commit()

        kb = await _my_bots_keyboard(session, user)
        if kb is None:
            await callback.message.edit_text(
                f"Sizda hali botlar yo'q. Yaratish uchun \"{MENU_NEW_BOT}\" tugmasini bosing."
            )
        else:
            await callback.message.edit_text("Sizning botlaringiz. Batafsil ma'lumot uchun bosing:", reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data.startswith("bot_detail:"))
    async def on_bot_detail(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        await state.clear()  # bot kartasini ochish — har qanday chek/tarif oqimini bekor qiladi
        bot_id = int(callback.data.split(":", 1)[1])
        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        try:
            text, payment_status = await _format_bot_detail(session, bot_row)
        except LimitExceededError as exc:
            await callback.answer(f"Xatolik: {exc}", show_alert=True)
            return

        await callback.message.edit_text(text, reply_markup=_bot_detail_keyboard(bot_id, payment_status))
        await callback.answer()

    # --- 💳 To'lov cheki yuborish (oylik hosting) ---

    @router.callback_query(F.data.startswith("pay_hosting:"))
    async def on_pay_hosting(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        bot_id = int(callback.data.split(":", 1)[1])
        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        status = await hosting_payment_status_this_month(session, bot_id)
        if status in (PaymentStatus.PENDING, PaymentStatus.APPROVED):
            hint = "kutilmoqda" if status == PaymentStatus.PENDING else "allaqachon to'langan"
            await callback.answer(f"Bu oy uchun to'lov {hint}.", show_alert=True)
            return

        await state.clear()
        await state.update_data(payment_bot_id=bot_id)
        await state.set_state(PaymentStates.waiting_for_hosting_receipt)
        await callback.answer()
        await callback.message.answer("To'lov chekining skrinshotini shu yerga RASM qilib yuboring:")

    @router.message(PaymentStates.waiting_for_hosting_receipt, F.photo)
    async def on_hosting_receipt(message: Message, state: FSMContext, session: AsyncSession, bot: AiogramBot) -> None:
        data = await state.get_data()
        bot_id = data.get("payment_bot_id")
        file_id = message.photo[-1].file_id

        try:
            _, amount = await submit_hosting_payment(session, bot_id, file_id)
        except HostingPaymentAlreadyExistsError:
            await message.answer("Bu oy uchun to'lov allaqachon yuborilgan.")
            await state.clear()
            return
        except LimitExceededError as exc:
            await message.answer(f"Xatolik: {exc}")
            await state.clear()
            return

        await state.clear()
        await message.answer(
            f"✅ Chekingiz qabul qilindi ({int(amount)} so'm). Admin ko'rib chiqqach xabar beriladi."
        )
        await _notify_admins_new_payment(session, bot, bot_id, "Oylik hosting to'lovi", amount, file_id)

    @router.message(PaymentStates.waiting_for_hosting_receipt)
    async def on_hosting_receipt_invalid(message: Message) -> None:
        await message.answer("Iltimos, chekning skrinshotini RASM ko'rinishida yuboring.")

    # --- ⬆️ Tarifni oshirish ---

    @router.callback_query(F.data.startswith("pay_upgrade:"))
    async def on_pay_upgrade(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        bot_id = int(callback.data.split(":", 1)[1])
        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        try:
            current_tariff = await get_active_tariff(session, bot_id)
        except LimitExceededError as exc:
            await callback.answer(f"Xatolik: {exc}", show_alert=True)
            return

        all_tariffs = await _get_all_tariffs(session)
        other_tariffs = [t for t in all_tariffs if t.code != current_tariff.code]
        if not other_tariffs:
            await callback.answer("Boshqa tarif mavjud emas.", show_alert=True)
            return

        await state.clear()
        await state.update_data(payment_bot_id=bot_id)
        await state.set_state(PaymentStates.waiting_for_upgrade_tariff)
        await callback.message.edit_text(
            "Qaysi tarifga o'tmoqchisiz? Batafsil ma'lumot uchun bosing:",
            reply_markup=_upgrade_tariff_keyboard(bot_id, other_tariffs),
        )
        await callback.answer()

    @router.callback_query(PaymentStates.waiting_for_upgrade_tariff, F.data.startswith("upg_tariff_view:"))
    async def on_upg_tariff_view(callback: CallbackQuery, session: AsyncSession) -> None:
        code = TariffCode(callback.data.split(":", 1)[1])
        tariff = await get_tariff_by_code(session, code)

        kb = InlineKeyboardBuilder()
        kb.button(text=f"✅ {tariff.name} tarifini tanlash", callback_data=f"upg_tariff_pick:{code.value}")
        kb.button(text="⬅️ Orqaga", callback_data="upg_tariff_back")
        kb.adjust(1)

        await callback.message.edit_text(_format_tariff_detail(tariff), reply_markup=kb.as_markup())
        await callback.answer()

    @router.callback_query(PaymentStates.waiting_for_upgrade_tariff, F.data == "upg_tariff_back")
    async def on_upg_tariff_back(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        data = await state.get_data()
        bot_id = data.get("payment_bot_id")

        try:
            current_tariff = await get_active_tariff(session, bot_id)
        except LimitExceededError as exc:
            await callback.answer(f"Xatolik: {exc}", show_alert=True)
            return

        all_tariffs = await _get_all_tariffs(session)
        other_tariffs = [t for t in all_tariffs if t.code != current_tariff.code]
        await callback.message.edit_text(
            "Qaysi tarifga o'tmoqchisiz? Batafsil ma'lumot uchun bosing:",
            reply_markup=_upgrade_tariff_keyboard(bot_id, other_tariffs),
        )
        await callback.answer()

    @router.callback_query(PaymentStates.waiting_for_upgrade_tariff, F.data.startswith("upg_tariff_pick:"))
    async def on_upg_tariff_pick(callback: CallbackQuery, state: FSMContext) -> None:
        code = callback.data.split(":", 1)[1]
        await state.update_data(target_tariff_code=code)
        await state.set_state(PaymentStates.waiting_for_upgrade_receipt)
        await callback.message.edit_text("Endi to'lov chekining skrinshotini shu yerga RASM qilib yuboring:")
        await callback.answer()

    @router.message(PaymentStates.waiting_for_upgrade_receipt, F.photo)
    async def on_upgrade_receipt(message: Message, state: FSMContext, session: AsyncSession, bot: AiogramBot) -> None:
        data = await state.get_data()
        bot_id = data.get("payment_bot_id")
        target_tariff_code = TariffCode(data.get("target_tariff_code"))
        file_id = message.photo[-1].file_id

        try:
            _, amount = await submit_tariff_upgrade(session, bot_id, target_tariff_code, file_id)
        except LimitExceededError as exc:
            await message.answer(f"Xatolik: {exc}")
            await state.clear()
            return

        await state.clear()
        tariff = await get_tariff_by_code(session, target_tariff_code)
        await message.answer(
            f"✅ Chekingiz qabul qilindi ({int(amount)} so'm, {tariff.name} tarifi). "
            "Admin ko'rib chiqqach xabar beriladi."
        )
        await _notify_admins_new_payment(
            session, bot, bot_id, f"Tarif oshirish → {tariff.name}", amount, file_id
        )

    @router.message(PaymentStates.waiting_for_upgrade_receipt)
    async def on_upgrade_receipt_invalid(message: Message) -> None:
        await message.answer("Iltimos, chekning skrinshotini RASM ko'rinishida yuboring.")

    @router.message(
        StateFilter(
            PaymentStates.waiting_for_hosting_receipt,
            PaymentStates.waiting_for_upgrade_tariff,
            PaymentStates.waiting_for_upgrade_receipt,
        ),
        F.text.startswith("/") | F.text.in_(_RESERVED_MENU_TEXTS),
    )
    async def on_command_while_waiting_payment(message: Message, state: FSMContext) -> None:
        """To'lov oqimida (chek kutish/tarif tanlash) boshqa buyruq/menyu tugmasi
        bosilsa — oqim bekor qilinadi, buyruq oddiy tarzda bajariladi."""
        await state.clear()
        await message.answer("Amal bekor qilindi. Qaytadan boshlash uchun bot kartasini oching.")

    async def _start_new_bot_flow(message: Message, state: FSMContext, session: AsyncSession) -> None:
        user = await get_or_create_user(session, telegram_id=message.from_user.id)
        await session.commit()

        if not user.registration_completed:
            await message.answer("Avval qisqa ro'yxatdan o'ting: /start")
            return

        await state.clear()  # boshqa oqim (masalan to'lov kutish) qolib ketmasligi uchun
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
