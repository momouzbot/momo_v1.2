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
from app.models.base import BillingPeriod, BotStatus, ModuleType, PaymentStatus, TariffCode
from app.models.bot import Bot as BotModel
from app.models.broadcast import BroadcastLog
from app.models.module import Module
from app.models.payment import Payment
from app.models.tariff import Tariff
from app.models.user import User
from app.services.limits import (
    LimitExceededError,
    TARIFF_RANK,
    calculate_hosting_price,
    check_and_increment_edit_limit,
    get_hosting_grace_days_remaining,
    get_owner_effective_bot_tariff,
    get_owner_effective_tariff,
    get_tariff_by_code,
    get_unique_user_count,
)
from app.services.modules import list_modules, set_module_active
from app.services.payments import (
    HostingPaymentAlreadyExistsError,
    NotAuthorizedError,
    PaymentNotFoundError,
    approve_payment,
    get_hosting_coverage,
    get_payment_amount_and_label,
    get_payment_with_context,
    list_pending_payments,
    reject_payment,
    submit_hosting_payment,
    submit_tariff_upgrade,
)
from app.services.crypto import decrypt_token
from app.services.registration import AlreadyRegisteredError, register_bot_for_owner
from app.services.platform_settings import format_payment_details, get_platform_settings, update_payment_details
from app.services.stats import get_platform_stats
from app.services.tariffs import TARIFF_FIELDS, InvalidTariffFieldError, update_tariff_field
from app.services.telegram import InvalidTokenError, delete_webhook, set_webhook
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


class AdminPaymentStates(StatesGroup):
    """Admin panel — to'lovni rad etish sababini kiritish oqimi."""

    waiting_for_rejection_reason = State()


class AdminTariffStates(StatesGroup):
    """Admin panel — ta'rif maydonini tahrirlash oqimi."""

    waiting_for_field_value = State()


class AdminPaymentDetailsStates(StatesGroup):
    """Admin panel — to'lov rekvizitlarini (karta) tahrirlash oqimi."""

    waiting_for_card_number = State()
    waiting_for_card_holder = State()
    waiting_for_instructions = State()


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
    builder.button(text="⬅️ Orqaga", callback_data="admin_menu:back")
    builder.adjust(1)
    return builder.as_markup()


def _admin_main_menu_keyboard(pending_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🧩 Modullar", callback_data="admin_menu:modules")
    payments_label = f"💳 To'lovlar ({pending_count} ta kutilmoqda)" if pending_count else "💳 To'lovlar"
    builder.button(text=payments_label, callback_data="admin_menu:payments")
    builder.button(text="💰 Ta'riflar", callback_data="admin_menu:tariffs")
    builder.button(text="📊 Statistika", callback_data="admin_menu:stats")
    builder.button(text="💳 To'lov rekvizitlari", callback_data="admin_menu:payment_details")
    builder.button(text="✖️ Yopish", callback_data="admin_menu:close")
    builder.adjust(1)
    return builder.as_markup()


def _admin_payments_list_keyboard(payments_info: list[tuple[Payment, float, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for payment, amount, label in payments_info:
        builder.button(text=f"#{payment.id} — {label} — {int(amount)} so'm", callback_data=f"payment_view:{payment.id}")
    builder.button(text="⬅️ Orqaga", callback_data="admin_menu:back")
    builder.adjust(1)
    return builder.as_markup()


def _payment_detail_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Tasdiqlash", callback_data=f"payment_approve:{payment_id}")
    builder.button(text="❌ Rad etish", callback_data=f"payment_reject:{payment_id}")
    builder.adjust(2)
    return builder.as_markup()


def _admin_tariffs_list_keyboard(tariffs: list[Tariff]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in tariffs:
        hint = "bepul" if t.code == TariffCode.START else f"{int(t.base_hosting_price)} so'm/oy"
        builder.button(text=f"{t.name} — {hint}", callback_data=f"admin_tariff_view:{t.code.value}")
    builder.button(text="⬅️ Orqaga", callback_data="admin_menu:back")
    builder.adjust(1)
    return builder.as_markup()


def _admin_tariff_detail_keyboard(code: TariffCode) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field_name, meta in TARIFF_FIELDS.items():
        builder.button(text=f"✏️ {meta['label']}", callback_data=f"admin_tariff_edit:{code.value}:{field_name}")
    builder.button(text="⬅️ Orqaga", callback_data="admin_menu:tariffs")
    builder.adjust(1)
    return builder.as_markup()


def _format_tariff_detail(t: Tariff) -> str:
    lines = [f"📦 {t.name} tarifi"]
    if t.description:
        lines.append(t.description)
    lines.append(f"• Bot soni: {t.bot_limit} ta")
    lines.append(f"• Kunlik tahrir limiti: {t.edit_limit_per_day} marta")
    lines.append(f"• Muddat: {t.duration_days} kun" if t.duration_days else "• Muddat: muddatsiz")
    if t.duration_days and t.grace_period_days:
        lines.append(f"• Muddat tugagach imtiyoz: yana {t.grace_period_days} kun faol qoladi")
    if float(t.upgrade_price) > 0:
        lines.append(f"• Tarifga o'tish narxi: {int(t.upgrade_price)} so'm")
    lines.append(
        f"• Hosting narxi ({t.user_threshold} foydalanuvchigacha): "
        f"haftasiga {int(t.weekly_hosting_price)} so'm / oyiga {int(t.base_hosting_price)} so'm"
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
    BotStatus.SUSPENDED: "⛔ To'xtatilgan (tarif muddati tugab, bot limitidan oshgan)",
    BotStatus.DELETED: "🗑 O'chirilgan",
}

_HOSTING_STATUS_WORD = {
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
    result = await session.execute(
        select(BotModel).where(BotModel.owner_id == user.id, BotModel.status != BotStatus.DELETED)
    )
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
    """Bot uchun to'liq holat matnini qaytaradi: tarif, tugash sanasi, joriy
    davr foydalanuvchilari/narxi (haftalik va oylik ikkalasi ham) va hosting
    to'lovi holati — barchasi bazadan real vaqtda hisoblanadi."""
    tariff = await get_owner_effective_tariff(session, bot_row.owner_id)
    bot_tariff_row = await get_owner_effective_bot_tariff(session, bot_row.owner_id)
    unique_users = await get_unique_user_count(session, bot_row.id)
    weekly_price = await calculate_hosting_price(session, bot_row.id, unique_users, BillingPeriod.WEEKLY)
    monthly_price = await calculate_hosting_price(session, bot_row.id, unique_users, BillingPeriod.MONTHLY)
    payment_status, period_end, billing_period = await get_hosting_coverage(session, bot_row.id)

    expires_label = (
        bot_tariff_row.expires_at.strftime("%Y-%m-%d") if bot_tariff_row.expires_at else "Muddatsiz"
    )
    label = _MODULE_LABELS.get(bot_row.module_type, bot_row.module_type.value)
    status_label = _BOT_STATUS_LABEL.get(bot_row.status, bot_row.status.value)

    if payment_status is None:
        grace_days = get_hosting_grace_days_remaining(bot_row, tariff)
        if grace_days > 0:
            payment_label = f"🎁 Bepul sinov davrida (yana {grace_days} kun)"
        else:
            payment_label = "❌ To'lanmagan"
    else:
        period_word = "Haftalik" if billing_period == BillingPeriod.WEEKLY else "Oylik"
        status_word = _HOSTING_STATUS_WORD[payment_status]
        until = f" ({period_end.strftime('%Y-%m-%d')} gacha)" if payment_status == PaymentStatus.APPROVED else ""
        payment_label = f"{status_word} — {period_word}{until}"

    lines = [
        f"🤖 @{bot_row.username}",
        f"Turi: {label}",
        f"Holat: {status_label}",
        "",
        f"📦 Tarif: {tariff.name}",
        f"📅 Tugash sanasi: {expires_label}",
        "",
        f"👥 Joriy davr foydalanuvchilari: {unique_users} ta",
        f"💰 Hosting narxi: haftasiga {int(weekly_price)} so'm / oyiga {int(monthly_price)} so'm",
        f"💳 Hosting to'lovi: {payment_label}",
    ]
    return "\n".join(lines), payment_status


def _bot_detail_keyboard(bot_id: int, bot_status: BotStatus, payment_status: PaymentStatus | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if bot_status == BotStatus.SUSPENDED:
        # SUSPENDED — tarif muddati tugab, bot limitidan oshgani uchun
        # to'xtatilgan; buni hosting to'lovi emas, faqat tarifni oshirish
        # (bot limitini ko'paytirish) tiklaydi.
        builder.button(text="⬆️ Tarifni oshirish", callback_data=f"pay_upgrade:{bot_id}")
    else:
        if payment_status in (None, PaymentStatus.REJECTED):
            builder.button(text="💳 To'lov cheki yuborish", callback_data=f"pay_hosting:{bot_id}")
        builder.button(text="⬆️ Tarifni oshirish", callback_data=f"pay_upgrade:{bot_id}")
    builder.button(text="📨 Xabarlar tarixi", callback_data=f"broadcast_stats:{bot_id}")
    if bot_status == BotStatus.ACTIVE:
        # Bot "faol" deb ko'rsatilsa ham, Telegram webhookni o'z tomonidan
        # (masalan uzoq vaqt xato qaytargani uchun) o'chirib qo'ygan bo'lishi
        # mumkin — bu tugma orqali mijoz o'zi, hech kimni kutmasdan qayta
        # ulay oladi.
        builder.button(text="🔄 Webhookni qayta ulash", callback_data=f"restart_webhook:{bot_id}")
    builder.button(text="🗑 Botni o'chirish", callback_data=f"delete_bot_confirm:{bot_id}")
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

        await callback.message.edit_text(
            text, reply_markup=_bot_detail_keyboard(bot_id, bot_row.status, payment_status)
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("broadcast_stats:"))
    async def on_broadcast_stats(callback: CallbackQuery, session: AsyncSession) -> None:
        bot_id = int(callback.data.split(":", 1)[1])
        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        try:
            await check_and_increment_edit_limit(session, bot_id)
        except LimitExceededError as exc:
            await callback.answer(f"Kunlik tahrirlash limitiga yetdingiz: {exc}", show_alert=True)
            return

        result = await session.execute(
            select(BroadcastLog).where(BroadcastLog.bot_id == bot_id).order_by(BroadcastLog.created_at.desc()).limit(5)
        )
        logs = result.scalars().all()

        if not logs:
            text = "📨 Bu bot hali ommaviy xabar yubormagan."
        else:
            lines = ["📨 So'nggi ommaviy xabarlar:\n"]
            for log in logs:
                date_label = log.created_at.strftime("%Y-%m-%d %H:%M")
                lines.append(
                    f"• {date_label} — {log.success_count}/{log.total_recipients} yetib bordi "
                    f"({log.failed_count} yetmadi)"
                )
            text = "\n".join(lines)

        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Orqaga", callback_data=f"bot_detail:{bot_id}")
        kb.adjust(1)
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
        await callback.answer()

    @router.callback_query(F.data.startswith("restart_webhook:"))
    async def on_restart_webhook(callback: CallbackQuery, session: AsyncSession) -> None:
        bot_id = int(callback.data.split(":", 1)[1])
        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        try:
            token = decrypt_token(bot_row.token_encrypted)
            await set_webhook(token, bot_row.telegram_bot_id)
        except Exception:
            logger.exception("Webhookni qayta ulashda xato: bot_id=%s", bot_row.telegram_bot_id)
            await callback.answer("Xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.", show_alert=True)
            return

        await callback.answer("✅ Webhook qayta ulandi.", show_alert=True)
        await callback.message.answer(
            "✅ Webhook qayta ulandi. Botingizga /start yuborib tekshiring.\n\n"
            "❗️Agar bot hali ham javob bermasa, ehtimol bot tokeningiz BotFather "
            "orqali bekor qilingan (revoke qilingan) yoki boshqa sababdan yaroqsiz "
            "bo'lib qolgan. Bunday holatda pastdagi \"🗑 Botni o'chirish\" tugmasi "
            "orqali eski botni o'chirib, BotFather'dan yangi token olib, "
            "\"➕ Yangi bot\" orqali qaytadan ulashingiz mumkin."
        )

    # --- 🗑 Botni o'chirish ---

    @router.callback_query(F.data.startswith("delete_bot_confirm:"))
    async def on_delete_bot_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
        bot_id = int(callback.data.split(":", 1)[1])
        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Ha, o'chirish", callback_data=f"delete_bot_execute:{bot_id}")
        kb.button(text="❌ Yo'q, bekor qilish", callback_data=f"bot_detail:{bot_id}")
        kb.adjust(1)
        await callback.message.edit_text(
            f"⚠️ @{bot_row.username} botini o'chirmoqchimisiz?\n\n"
            "Bu amalni ortga qaytarib bo'lmaydi — bot to'xtaydi va endi ishlamaydi. "
            "(Kino kabi ma'lumotlaringiz bazada saqlanib qoladi, lekin botning o'zi "
            "faollashmaydi.)\n\n"
            "O'chirilgach, shu tarifingiz doirasida darhol yangi bot (yangi token bilan) "
            "qo'sha olasiz.",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("delete_bot_execute:"))
    async def on_delete_bot_execute(callback: CallbackQuery, session: AsyncSession) -> None:
        bot_id = int(callback.data.split(":", 1)[1])
        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        try:
            token = decrypt_token(bot_row.token_encrypted)
            await delete_webhook(token)
        except Exception:
            logger.exception("Botni o'chirishda webhookni tozalashda xato: bot_id=%s", bot_row.telegram_bot_id)

        bot_row.status = BotStatus.DELETED
        await session.commit()

        await callback.answer("O'chirildi.")
        await callback.message.edit_text(
            f"🗑 @{bot_row.username} o'chirildi.\n\n"
            f"Yangi bot qo'shish uchun \"{MENU_NEW_BOT}\" tugmasini bosing."
        )

    # --- 💳 To'lov cheki yuborish (haftalik yoki oylik hosting) ---

    @router.callback_query(F.data.startswith("pay_hosting:"))
    async def on_pay_hosting(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        bot_id = int(callback.data.split(":", 1)[1])
        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        status, _, _ = await get_hosting_coverage(session, bot_id)
        if status in (PaymentStatus.PENDING, PaymentStatus.APPROVED):
            hint = "kutilmoqda" if status == PaymentStatus.PENDING else "allaqachon to'langan"
            await callback.answer(f"Bu davr uchun to'lov {hint}.", show_alert=True)
            return

        unique_users = await get_unique_user_count(session, bot_id)
        weekly_price = await calculate_hosting_price(session, bot_id, unique_users, BillingPeriod.WEEKLY)
        monthly_price = await calculate_hosting_price(session, bot_id, unique_users, BillingPeriod.MONTHLY)

        await state.clear()
        await state.update_data(payment_bot_id=bot_id)

        kb = InlineKeyboardBuilder()
        kb.button(text=f"📅 Haftalik — {int(weekly_price)} so'm", callback_data="hosting_period:weekly")
        kb.button(text=f"🗓 Oylik — {int(monthly_price)} so'm", callback_data="hosting_period:monthly")
        kb.button(text="⬅️ Orqaga", callback_data=f"bot_detail:{bot_id}")
        kb.adjust(1)

        await callback.message.edit_text(
            "Qaysi davr uchun to'lamoqchisiz?",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("hosting_period:"))
    async def on_hosting_period_chosen(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        billing_period = BillingPeriod(callback.data.split(":", 1)[1])
        await state.update_data(hosting_billing_period=billing_period.value)
        await state.set_state(PaymentStates.waiting_for_hosting_receipt)

        settings_row = await get_platform_settings(session)
        await callback.message.edit_text(
            f"{format_payment_details(settings_row)}\n\n"
            "To'lovni amalga oshirgach, chekning skrinshotini shu yerga RASM qilib yuboring:"
        )
        await callback.answer()

    @router.message(PaymentStates.waiting_for_hosting_receipt, F.photo)
    async def on_hosting_receipt(message: Message, state: FSMContext, session: AsyncSession, bot: AiogramBot) -> None:
        data = await state.get_data()
        bot_id = data.get("payment_bot_id")
        billing_period = BillingPeriod(data.get("hosting_billing_period"))
        file_id = message.photo[-1].file_id

        try:
            _, amount = await submit_hosting_payment(session, bot_id, billing_period, file_id)
        except HostingPaymentAlreadyExistsError:
            await message.answer("Bu davr uchun to'lov allaqachon yuborilgan.")
            await state.clear()
            return
        except LimitExceededError as exc:
            await message.answer(f"Xatolik: {exc}")
            await state.clear()
            return

        await state.clear()
        period_word = "Haftalik" if billing_period == BillingPeriod.WEEKLY else "Oylik"
        await message.answer(
            f"✅ Chekingiz qabul qilindi ({period_word.lower()}, {int(amount)} so'm). "
            "Admin ko'rib chiqqach xabar beriladi."
        )
        await _notify_admins_new_payment(session, bot, bot_id, f"{period_word} hosting to'lovi", amount, file_id)

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
            current_tariff = await get_owner_effective_tariff(session, bot_row.owner_id)
        except LimitExceededError as exc:
            await callback.answer(f"Xatolik: {exc}", show_alert=True)
            return

        all_tariffs = await _get_all_tariffs(session)
        other_tariffs = [
            t for t in all_tariffs if TARIFF_RANK.get(t.code, 0) > TARIFF_RANK.get(current_tariff.code, 0)
        ]
        if not other_tariffs:
            await callback.answer(
                "Sizda allaqachon eng yuqori faol tarif bor (boshqa botingiz orqali bo'lsa ham).",
                show_alert=True,
            )
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

        bot_row = await _get_owned_bot_or_none(session, callback.from_user.id, bot_id)
        if bot_row is None:
            await callback.answer("Bot topilmadi.", show_alert=True)
            return

        try:
            current_tariff = await get_owner_effective_tariff(session, bot_row.owner_id)
        except LimitExceededError as exc:
            await callback.answer(f"Xatolik: {exc}", show_alert=True)
            return

        all_tariffs = await _get_all_tariffs(session)
        other_tariffs = [
            t for t in all_tariffs if TARIFF_RANK.get(t.code, 0) > TARIFF_RANK.get(current_tariff.code, 0)
        ]
        await callback.message.edit_text(
            "Qaysi tarifga o'tmoqchisiz? Batafsil ma'lumot uchun bosing:",
            reply_markup=_upgrade_tariff_keyboard(bot_id, other_tariffs),
        )
        await callback.answer()

    @router.callback_query(PaymentStates.waiting_for_upgrade_tariff, F.data.startswith("upg_tariff_pick:"))
    async def on_upg_tariff_pick(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        code = callback.data.split(":", 1)[1]
        await state.update_data(target_tariff_code=code)
        await state.set_state(PaymentStates.waiting_for_upgrade_receipt)

        settings_row = await get_platform_settings(session)
        await callback.message.edit_text(
            f"{format_payment_details(settings_row)}\n\n"
            "To'lovni amalga oshirgach, chekning skrinshotini shu yerga RASM qilib yuboring:"
        )
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
            AdminPaymentStates.waiting_for_rejection_reason,
            AdminTariffStates.waiting_for_field_value,
        ),
        F.text.startswith("/") | F.text.in_(_RESERVED_MENU_TEXTS),
    )
    async def on_command_while_waiting_payment(message: Message, state: FSMContext) -> None:
        """To'lov yoki admin tahrirlash oqimida (chek kutish/tarif tanlash/qiymat
        kiritish) boshqa buyruq/menyu tugmasi bosilsa — oqim bekor qilinadi."""
        await state.clear()
        await message.answer("Amal bekor qilindi. Qaytadan boshlash uchun tegishli bo'limni qayta oching.")

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

    async def _send_admin_main_menu(message: Message, session: AsyncSession) -> None:
        pending_count = len(await list_pending_payments(session))
        await message.answer(
            "⚙️ Admin panel. Bo'limni tanlang:",
            reply_markup=_admin_main_menu_keyboard(pending_count),
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
            await _send_admin_main_menu(message, session)
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

        await _send_admin_main_menu(message, session)

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
    # Momo Admin: asosiy menyu navigatsiyasi (Modullar/To'lovlar/Ta'riflar/Statistika)
    # -----------------------------------------------------------------

    async def _require_momo_admin(callback: CallbackQuery, session: AsyncSession) -> User | None:
        user = await get_or_create_user(session, telegram_id=callback.from_user.id)
        await session.commit()
        if not user.is_momo_admin:
            await callback.answer("Bu amal faqat Momo Admin uchun.", show_alert=True)
            return None
        return user

    @router.callback_query(F.data == "admin_menu:back")
    async def on_admin_menu_back(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return
        await state.clear()
        pending_count = len(await list_pending_payments(session))
        await callback.message.edit_text(
            "⚙️ Admin panel. Bo'limni tanlang:",
            reply_markup=_admin_main_menu_keyboard(pending_count),
        )
        await callback.answer()

    @router.callback_query(F.data == "admin_menu:close")
    async def on_admin_menu_close(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.message.edit_text("Admin panel yopildi. Qaytadan ochish uchun /admin yuboring.")
        await callback.answer()

    @router.callback_query(F.data == "admin_menu:modules")
    async def on_admin_menu_modules(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return
        await state.clear()
        modules = await list_modules(session)
        if not modules:
            await callback.message.edit_text("Modullar ro'yxati bo'sh (seed ishga tushmagan bo'lishi mumkin).")
            await callback.answer()
            return
        await callback.message.edit_text(
            "Modullarni boshqarish. Bosilgan modul yoqiladi/o'chiriladi:\n"
            "(✅ = yoqilgan, foydalanuvchilarga ko'rinadi, ❌ = o'chirilgan)",
            reply_markup=_admin_modules_keyboard(modules),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin_toggle:"))
    async def on_admin_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
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
    # Momo Admin: 💳 To'lovlar — kutilayotgan cheklarni ko'rish, tasdiqlash/rad etish
    # -----------------------------------------------------------------

    @router.callback_query(F.data == "admin_menu:payments")
    async def on_admin_menu_payments(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return
        await state.clear()

        pending = await list_pending_payments(session)
        if not pending:
            kb = InlineKeyboardBuilder()
            kb.button(text="⬅️ Orqaga", callback_data="admin_menu:back")
            kb.adjust(1)
            await callback.message.edit_text("Hozircha kutilayotgan to'lovlar yo'q.", reply_markup=kb.as_markup())
            await callback.answer()
            return

        infos = [(p, *(await get_payment_amount_and_label(session, p))) for p in pending]
        await callback.message.edit_text(
            "Kutilayotgan to'lovlar. Batafsil ko'rish uchun bosing:",
            reply_markup=_admin_payments_list_keyboard(infos),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("payment_view:"))
    async def on_payment_view(callback: CallbackQuery, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return

        payment_id = int(callback.data.split(":", 1)[1])
        try:
            payment, bot_row, owner = await get_payment_with_context(session, payment_id)
        except PaymentNotFoundError:
            await callback.answer("To'lov topilmadi.", show_alert=True)
            return

        if payment.status != PaymentStatus.PENDING:
            await callback.answer("Bu to'lov allaqachon ko'rib chiqilgan.", show_alert=True)
            return

        amount, label = await get_payment_amount_and_label(session, payment)
        caption = (
            f"#{payment.id} — {label}\n\n"
            f"Bot: @{bot_row.username}\n"
            f"Mijoz: {owner.full_name or '—'} ({owner.phone_number or '—'})\n"
            f"Summa: {int(amount)} so'm"
        )
        await callback.message.answer_photo(
            payment.receipt_file_id, caption=caption, reply_markup=_payment_detail_keyboard(payment.id)
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("payment_approve:"))
    async def on_payment_approve(callback: CallbackQuery, session: AsyncSession, bot: AiogramBot) -> None:
        if await _require_momo_admin(callback, session) is None:
            return

        payment_id = int(callback.data.split(":", 1)[1])
        try:
            payment = await approve_payment(session, payment_id, callback.from_user.id)
        except PaymentNotFoundError:
            await callback.answer("To'lov topilmadi.", show_alert=True)
            return
        except NotAuthorizedError:
            await callback.answer("Ruxsat yo'q.", show_alert=True)
            return
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        amount, label = await get_payment_amount_and_label(session, payment)
        bot_result = await session.execute(select(BotModel).where(BotModel.id == payment.bot_id))
        bot_row = bot_result.scalar_one_or_none()
        if bot_row is not None:
            owner_result = await session.execute(select(User).where(User.id == bot_row.owner_id))
            owner = owner_result.scalar_one_or_none()
            if owner is not None:
                try:
                    await bot.send_message(
                        owner.telegram_id,
                        f"✅ To'lovingiz tasdiqlandi!\n{label} — {int(amount)} so'm.\n@{bot_row.username}",
                    )
                except Exception:
                    logger.exception("Mijozga to'lov tasdiqlangani haqida xabar yuborishda xato")

        old_caption = callback.message.caption or ""
        await callback.message.edit_caption(caption=f"✅ TASDIQLANDI\n\n{old_caption}", reply_markup=None)
        await callback.answer("Tasdiqlandi.")

    @router.callback_query(F.data.startswith("payment_reject:"))
    async def on_payment_reject(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return

        payment_id = int(callback.data.split(":", 1)[1])
        await state.clear()
        await state.update_data(reject_payment_id=payment_id)
        await state.set_state(AdminPaymentStates.waiting_for_rejection_reason)
        await callback.message.answer("Rad etish sababini yozing (mijozga shu matn yuboriladi):")
        await callback.answer()

    @router.message(AdminPaymentStates.waiting_for_rejection_reason)
    async def on_rejection_reason(message: Message, state: FSMContext, session: AsyncSession, bot: AiogramBot) -> None:
        data = await state.get_data()
        payment_id = data.get("reject_payment_id")
        reason = (message.text or "").strip()
        await state.clear()

        try:
            payment = await reject_payment(session, payment_id, message.from_user.id, reason or None)
        except PaymentNotFoundError:
            await message.answer("To'lov topilmadi.")
            return
        except NotAuthorizedError:
            await message.answer("Ruxsat yo'q.")
            return
        except ValueError as exc:
            await message.answer(str(exc))
            return

        amount, label = await get_payment_amount_and_label(session, payment)
        bot_result = await session.execute(select(BotModel).where(BotModel.id == payment.bot_id))
        bot_row = bot_result.scalar_one_or_none()
        if bot_row is not None:
            owner_result = await session.execute(select(User).where(User.id == bot_row.owner_id))
            owner = owner_result.scalar_one_or_none()
            if owner is not None:
                reason_line = f"\nSabab: {reason}" if reason else ""
                try:
                    await bot.send_message(
                        owner.telegram_id,
                        f"❌ To'lovingiz rad etildi.\n{label} — {int(amount)} so'm.{reason_line}\n\n"
                        "Qaytadan chek yuborishingiz mumkin.",
                    )
                except Exception:
                    logger.exception("Mijozga to'lov rad etilgani haqida xabar yuborishda xato")

        await message.answer(f"❌ To'lov #{payment.id} rad etildi.")

    # -----------------------------------------------------------------
    # Momo Admin: 💰 Ta'riflar — narx/limit/muddat/tavsifni tahrirlash
    # -----------------------------------------------------------------

    @router.callback_query(F.data == "admin_menu:tariffs")
    async def on_admin_menu_tariffs(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return
        await state.clear()
        tariffs = await _get_all_tariffs(session)
        await callback.message.edit_text(
            "Ta'riflarni boshqarish. Tahrirlash uchun tanlang:",
            reply_markup=_admin_tariffs_list_keyboard(tariffs),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin_tariff_view:"))
    async def on_admin_tariff_view(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return
        await state.clear()
        code = TariffCode(callback.data.split(":", 1)[1])
        tariff = await get_tariff_by_code(session, code)
        await callback.message.edit_text(
            _format_tariff_detail(tariff) + "\n\nQaysi maydonni o'zgartirmoqchisiz?",
            reply_markup=_admin_tariff_detail_keyboard(code),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("admin_tariff_edit:"))
    async def on_admin_tariff_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return

        _, code_value, field_name = callback.data.split(":", 2)
        if field_name not in TARIFF_FIELDS:
            await callback.answer("Noma'lum maydon.", show_alert=True)
            return

        await state.clear()
        await state.update_data(admin_tariff_code=code_value, admin_tariff_field=field_name)
        await state.set_state(AdminTariffStates.waiting_for_field_value)

        label = TARIFF_FIELDS[field_name]["label"]
        await callback.message.answer(f"{label} uchun yangi qiymatni kiriting:")
        await callback.answer()

    @router.message(AdminTariffStates.waiting_for_field_value)
    async def on_admin_tariff_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
        data = await state.get_data()
        code = TariffCode(data.get("admin_tariff_code"))
        field_name = data.get("admin_tariff_field")
        raw_value = (message.text or "").strip()

        try:
            tariff = await update_tariff_field(session, code, field_name, raw_value)
        except InvalidTariffFieldError as exc:
            await message.answer(f"Xatolik: {exc}\nQaytadan kiriting:")
            return  # holat o'zgarmaydi — admin qayta kiritishi mumkin
        except LimitExceededError as exc:
            await message.answer(f"Xatolik: {exc}")
            await state.clear()
            return

        await state.clear()
        await message.answer(
            f"✅ Yangilandi.\n\n{_format_tariff_detail(tariff)}",
            reply_markup=_admin_tariff_detail_keyboard(code),
        )

    # -----------------------------------------------------------------
    # Momo Admin: 📊 Statistika
    # -----------------------------------------------------------------

    @router.callback_query(F.data == "admin_menu:stats")
    async def on_admin_menu_stats(callback: CallbackQuery, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return

        stats = await get_platform_stats(session)
        status_line = ", ".join(
            f"{_BOT_STATUS_ICON.get(status, '?')} {count}" for status, count in stats["status_counts"].items()
        ) or "ma'lumot yo'q"
        tariff_line = ", ".join(
            f"{code.value} — {count}" for code, count in stats["tariff_counts"].items()
        ) or "ma'lumot yo'q"

        text = (
            "📊 Umumiy statistika\n\n"
            f"👥 Jami mijozlar: {stats['users_count']}\n"
            f"🤖 Jami botlar: {stats['bots_count']} ({status_line})\n"
            f"📦 Tariflar bo'yicha: {tariff_line}\n"
            f"💳 Kutilayotgan to'lovlar: {stats['pending_payments']} ta"
        )
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Orqaga", callback_data="admin_menu:back")
        kb.adjust(1)
        await callback.message.edit_text(text, reply_markup=kb.as_markup())
        await callback.answer()

    # -----------------------------------------------------------------
    # Momo Admin: 💳 To'lov rekvizitlari (mijoz qayerga to'lashini ko'rsatadi)
    # -----------------------------------------------------------------

    def _payment_details_keyboard() -> InlineKeyboardMarkup:
        kb = InlineKeyboardBuilder()
        kb.button(text="✏️ Tahrirlash", callback_data="payment_details_edit")
        kb.button(text="⬅️ Orqaga", callback_data="admin_menu:back")
        kb.adjust(1)
        return kb.as_markup()

    @router.callback_query(F.data == "admin_menu:payment_details")
    async def on_admin_menu_payment_details(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return
        await state.clear()

        settings_row = await get_platform_settings(session)
        text = "💳 To'lov rekvizitlari (mijozlarga shu ma'lumot ko'rsatiladi)\n\n" + format_payment_details(settings_row)
        await callback.message.edit_text(text, reply_markup=_payment_details_keyboard())
        await callback.answer()

    @router.callback_query(F.data == "payment_details_edit")
    async def on_payment_details_edit_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
        if await _require_momo_admin(callback, session) is None:
            return
        await state.clear()
        await state.set_state(AdminPaymentDetailsStates.waiting_for_card_number)
        await callback.message.answer("Karta raqamini kiriting (masalan: 8600 1234 5678 9012):")
        await callback.answer()

    @router.message(AdminPaymentDetailsStates.waiting_for_card_number)
    async def on_card_number_entered(message: Message, state: FSMContext) -> None:
        await state.update_data(card_number=(message.text or "").strip())
        await state.set_state(AdminPaymentDetailsStates.waiting_for_card_holder)
        await message.answer("Karta egasining F.I.Sh. kiriting:")

    @router.message(AdminPaymentDetailsStates.waiting_for_card_holder)
    async def on_card_holder_entered(message: Message, state: FSMContext) -> None:
        await state.update_data(card_holder=(message.text or "").strip())
        await state.set_state(AdminPaymentDetailsStates.waiting_for_instructions)
        await message.answer(
            "Qo'shimcha ko'rsatma kiriting (masalan bank nomi), yoki /otkazish bilan o'tkazib yuboring:"
        )

    @router.message(AdminPaymentDetailsStates.waiting_for_instructions, Command("otkazish"))
    async def on_instructions_skipped(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _finish_payment_details(message, state, session, instructions=None)

    @router.message(AdminPaymentDetailsStates.waiting_for_instructions)
    async def on_instructions_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
        await _finish_payment_details(message, state, session, instructions=(message.text or "").strip())

    async def _finish_payment_details(
        message: Message, state: FSMContext, session: AsyncSession, instructions: str | None
    ) -> None:
        data = await state.get_data()
        await state.clear()
        settings_row = await update_payment_details(
            session, data.get("card_number"), data.get("card_holder"), instructions
        )
        await message.answer(
            "✅ To'lov rekvizitlari yangilandi.\n\n" + format_payment_details(settings_row),
            reply_markup=_payment_details_keyboard(),
        )

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
