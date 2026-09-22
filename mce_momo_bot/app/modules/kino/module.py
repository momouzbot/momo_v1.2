"""
KinoBotModule (`kino`) — TZ 4.3-bo'lim.

Foydalanuvchi uchun:
    /start        — xush kelibsiz (owner bo'lsa — pastda "Admin panel" tugmasi ham chiqadi)
    <kod>         — kino kodini yuborsa, mos kino topilib yuboriladi
    /qidir <nom>  — nom bo'yicha qidiruv (inline natijalar ro'yxati)
    /top          — eng ko'p ko'rilgan 10 ta kino

Bot egasi uchun (faqat owner_telegram_id mos kelsa):
    /panel                — boshqaruv paneli (qo'shish / o'chirish / ro'yxat / statistika)
    /kino_qoshish          — FSM orqali yangi kino qo'shish (kod → nom → kategoriya → media)
    /kino_ochirish <kod>   — kinoni o'chirish (tasdiqlash so'raladi)
    /bekor                 — joriy jarayonni (qo'shish) bekor qilish

Kunlik kino qo'shish limiti — 10/kun, MIJOZNING TARIFIDAN QAT'I NAZAR bir xil
(kinobot moduli yakuniy tahrir rejasi). Bu Momo tarifining umumiy tahrir
limitidan (Tariff.edit_limit_per_day) ALOHIDA — app/services/feature_limits.py
orqali hisoblanadi. Bu limit serverni ortiqcha yuklanishdan himoya qilish
uchun ham kerak (mijozlar cheksiz fayl yuklab, xotira/diskni band qilib
qo'ymasligi uchun).
Premium obuna tizimi (bot egasining O'Z tomoshabinlari to'laydigan ichki
xizmat, Momo to'lov tizimidan mustaqil):
    /premium_narx  — bot egasi uchun: narx/muddat belgilash, yoqish/o'chirish
    /premium       — oddiy foydalanuvchi uchun: obuna bo'lish (chek yuborish)
    /premium_tolovlar — bot egasi uchun: kutilayotgan cheklarni ko'rish
"""
from __future__ import annotations

import datetime
import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.movie import Movie
from app.models.user import User
from app.modules.base import BaseModule
from app.services.feature_limits import check_and_increment_feature_limit
from app.services.limits import LimitExceededError, check_and_increment_edit_limit
from app.services.ownership import is_bot_owner, is_bot_owner_or_sub_admin
from app.services.premium_subscription import (
    PremiumPaymentNotFoundError,
    approve_premium_payment,
    get_premium_expiry,
    get_premium_settings,
    has_active_premium,
    list_pending_premium_payments,
    reject_premium_payment,
    set_premium_settings,
    submit_premium_payment,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 10

# Kunlik kino qo'shish limiti — hamma mijoz uchun bir xil (tarifga bog'liq emas)
KINO_QOSHISH_FEATURE_KEY = "kino_qoshish"
KINO_QOSHISH_DAILY_LIMIT = 10


class KinoStates(StatesGroup):
    waiting_code = State()
    waiting_title = State()
    waiting_category = State()
    waiting_premium_choice = State()
    waiting_media = State()


class PremiumStates(StatesGroup):
    """Premium obuna tizimi — TZ: "kinobot moduli yakuniy tahrir rejasi"."""

    waiting_for_price = State()       # bot egasi: narx kiritish
    waiting_for_duration = State()    # bot egasi: muddat (kun) kiritish
    waiting_for_receipt = State()     # oddiy foydalanuvchi: chek yuborish


def _movie_caption(movie: Movie) -> str:
    category = f"\n🏷 Kategoriya: {movie.category}" if movie.category else ""
    premium = "\n⭐ Premium kino" if movie.is_premium else ""
    return f"🎬 {movie.title}{category}{premium}\n🔑 Kod: {movie.code}\n👁 Ko'rishlar: {movie.views}"


def _escape_like(value: str) -> str:
    """LIKE maxsus belgilarini ('%', '_') qochiradi — foydalanuvchi shu belgilarni
    kiritsa ham, qidiruv so'zma-so'z (literal) ishlashi uchun."""
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _cancel_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="kino_cancel"))
    return builder


def _admin_panel_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Kino qo'shish", callback_data="kino_admin_add"),
        InlineKeyboardButton(text="🗑 Kino o'chirish", callback_data="kino_admin_delete:0"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Ro'yxat", callback_data="kino_admin_list:0"),
        InlineKeyboardButton(text="📊 Statistika", callback_data="kino_admin_stats"),
    )
    return builder


def _admin_panel_text() -> str:
    return (
        "🛠 Boshqaruv paneli\n\n"
        "Pastdagi tugmalar orqali asosiy amallarni bajarasiz. Bulardan tashqari "
        "quyidagi buyruqlar ham mavjud:\n\n"
        "📡 /kanallar — majburiy obuna kanallarini boshqarish\n"
        "📨 /xabar — barcha foydalanuvchilarga ommaviy xabar yuborish\n"
        "⭐ /premium_narx — Premium obuna narxini sozlash\n"
        "💳 /premium_tolovlar — kutilayotgan Premium to'lovlar\n"
        "👥 /moderatorlar — yordamchi adminlar (sub-admin) tayinlash"
    )


class KinoModule(BaseModule):
    def register_handlers(self, dp: Dispatcher) -> None:
        router = Router(name=f"kino_{self.bot_row.id}")
        bot_row = self.bot_row

        # ---------------------------------------------------------------
        # Foydalanuvchi buyruqlari
        # ---------------------------------------------------------------

        @router.message(CommandStart())
        async def cmd_start(message: Message, session: AsyncSession) -> None:
            await message.answer(
                "🎬 Kino-botga xush kelibsiz!\n\n"
                "Kino kodini yuboring — men sizga filmni topib beraman.\n"
                "Nom bo'yicha qidirish uchun: /qidir <nom>\n"
                "Top-10 kinolarni ko'rish: /top"
            )
            if await is_bot_owner_or_sub_admin(session, bot_row.id, message.from_user.id):
                await message.answer(_admin_panel_text(), reply_markup=_admin_panel_keyboard().as_markup())

        @router.message(Command("panel", "admin", "boshqaruv"))
        async def cmd_panel(message: Message, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, message.from_user.id):
                await message.answer("⛔ Bu buyruq faqat bot egasi uchun.")
                return
            await message.answer(_admin_panel_text(), reply_markup=_admin_panel_keyboard().as_markup())

        @router.message(Command("top"))
        async def cmd_top(message: Message, session: AsyncSession) -> None:
            result = await session.execute(
                select(Movie)
                .where(Movie.bot_id == bot_row.id)
                .order_by(Movie.views.desc())
                .limit(10)
            )
            movies = result.scalars().all()

            if not movies:
                await message.answer("Hozircha kinolar mavjud emas.")
                return

            lines = ["🏆 Top-10 eng ko'p ko'rilgan kinolar:\n"]
            for i, movie in enumerate(movies, start=1):
                lines.append(f"{i}. {movie.title} — 🔑 {movie.code} (👁 {movie.views})")
            await message.answer("\n".join(lines))

        @router.message(Command("qidir"))
        async def cmd_search(message: Message, command: CommandObject, session: AsyncSession) -> None:
            query = (command.args or "").strip()
            if not query:
                await message.answer("Qidiruv uchun nom kiriting: /qidir <nom>")
                return

            result = await session.execute(
                select(Movie)
                .where(
                    Movie.bot_id == bot_row.id,
                    Movie.title.ilike(f"%{_escape_like(query)}%", escape="\\"),
                )
                .order_by(Movie.views.desc())
                .limit(10)
            )
            movies = result.scalars().all()

            if not movies:
                await message.answer("Hech narsa topilmadi. Boshqa nom bilan urinib ko'ring.")
                return

            builder = InlineKeyboardBuilder()
            for movie in movies:
                builder.row(
                    InlineKeyboardButton(
                        text=f"{movie.title} ({movie.code})", callback_data=f"kino_get:{movie.code}"
                    )
                )
            await message.answer("🔍 Natijalar:", reply_markup=builder.as_markup())

        @router.callback_query(F.data.startswith("kino_get:"))
        async def on_result_click(callback: CallbackQuery, session: AsyncSession, bot: AiogramBot) -> None:
            code = callback.data.split(":", 1)[1]
            await _send_movie_by_code(session, bot, callback.message.chat.id, bot_row.id, code)
            await callback.answer()

        # ---------------------------------------------------------------
        # Admin panel (inline tugmalar) — faqat bot egasi uchun
        # ---------------------------------------------------------------

        @router.callback_query(F.data == "kino_admin_add")
        async def on_admin_add(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, callback.from_user.id):
                await callback.answer("⛔ Ruxsat yo'q.", show_alert=True)
                return
            await callback.answer()
            await _start_add_flow(callback.message, state)

        @router.callback_query(F.data.startswith("kino_admin_delete:"))
        async def on_admin_delete_list(callback: CallbackQuery, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, callback.from_user.id):
                await callback.answer("⛔ Ruxsat yo'q.", show_alert=True)
                return
            page = int(callback.data.split(":", 1)[1])
            await _render_delete_list(callback, session, bot_row.id, page)
            await callback.answer()

        @router.callback_query(F.data.startswith("kino_admin_del_confirm:"))
        async def on_admin_delete_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, callback.from_user.id):
                await callback.answer("⛔ Ruxsat yo'q.", show_alert=True)
                return
            code = callback.data.split(":", 1)[1]
            result = await session.execute(select(Movie).where(Movie.bot_id == bot_row.id, Movie.code == code))
            movie = result.scalar_one_or_none()
            if movie is None:
                await callback.answer("Topilmadi (allaqachon o'chirilgan bo'lishi mumkin).", show_alert=True)
                return

            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"kino_admin_del_do:{code}"))
            builder.row(InlineKeyboardButton(text="↩️ Bekor", callback_data="kino_admin_delete:0"))
            await callback.message.edit_text(
                f"«{movie.title}» (kod: {code}) rostdan o'chirilsinmi? Bu amalni qaytarib bo'lmaydi.",
                reply_markup=builder.as_markup(),
            )
            await callback.answer()

        @router.callback_query(F.data.startswith("kino_admin_del_do:"))
        async def on_admin_delete_do(callback: CallbackQuery, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, callback.from_user.id):
                await callback.answer("⛔ Ruxsat yo'q.", show_alert=True)
                return
            code = callback.data.split(":", 1)[1]
            result = await session.execute(select(Movie).where(Movie.bot_id == bot_row.id, Movie.code == code))
            movie = result.scalar_one_or_none()
            if movie is None:
                await callback.answer("Topilmadi.", show_alert=True)
                return

            title = movie.title
            await session.delete(movie)
            await session.commit()
            await callback.answer(f"🗑 «{title}» o'chirildi.", show_alert=True)
            await _render_delete_list(callback, session, bot_row.id, 0)

        @router.callback_query(F.data.startswith("kino_admin_list:"))
        async def on_admin_list(callback: CallbackQuery, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, callback.from_user.id):
                await callback.answer("⛔ Ruxsat yo'q.", show_alert=True)
                return
            page = int(callback.data.split(":", 1)[1])
            await _render_movie_list(callback, session, bot_row.id, page)
            await callback.answer()

        @router.callback_query(F.data == "kino_admin_stats")
        async def on_admin_stats(callback: CallbackQuery, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, callback.from_user.id):
                await callback.answer("⛔ Ruxsat yo'q.", show_alert=True)
                return

            result = await session.execute(
                select(func.count(), func.coalesce(func.sum(Movie.views), 0)).where(Movie.bot_id == bot_row.id)
            )
            total_movies, total_views = result.one()

            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kino_admin_back"))
            await callback.message.edit_text(
                f"📊 Statistika:\n\n🎬 Kinolar soni: {total_movies}\n👁 Umumiy ko'rishlar: {total_views}",
                reply_markup=builder.as_markup(),
            )
            await callback.answer()

        @router.callback_query(F.data == "kino_admin_back")
        async def on_admin_back(callback: CallbackQuery) -> None:
            await callback.message.edit_text("🛠 Boshqaruv paneli:", reply_markup=_admin_panel_keyboard().as_markup())
            await callback.answer()

        @router.callback_query(F.data == "kino_cancel")
        async def on_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
            await state.clear()
            await callback.message.edit_text("❌ Bekor qilindi.")
            await callback.answer()

        # ---------------------------------------------------------------
        # Bot egasi uchun: kino qo'shish (FSM)
        # ---------------------------------------------------------------

        @router.message(Command("kino_qoshish"))
        async def cmd_add_movie_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, message.from_user.id):
                await message.answer("⛔ Bu buyruq faqat bot egasi uchun.")
                return
            await _start_add_flow(message, state)

        @router.message(
            Command("bekor"),
            StateFilter(
                KinoStates.waiting_code,
                KinoStates.waiting_title,
                KinoStates.waiting_category,
                KinoStates.waiting_media,
            ),
        )
        async def cmd_cancel(message: Message, state: FSMContext) -> None:
            await state.clear()
            await message.answer("❌ Bekor qilindi.")

        @router.message(KinoStates.waiting_code)
        async def on_code_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
            code = (message.text or "").strip()
            if not code:
                await message.answer("Kod bo'sh bo'lmasligi kerak. Qaytadan kiriting:")
                return

            existing = await session.execute(
                select(Movie).where(Movie.bot_id == bot_row.id, Movie.code == code)
            )
            if existing.scalar_one_or_none() is not None:
                await message.answer("⚠️ Bu kod band. Boshqa kod kiriting:")
                return

            await state.update_data(code=code)
            await state.set_state(KinoStates.waiting_title)
            await message.answer("Kino nomini kiriting:", reply_markup=_cancel_keyboard().as_markup())

        @router.message(KinoStates.waiting_title)
        async def on_title_entered(message: Message, state: FSMContext) -> None:
            title = (message.text or "").strip()
            if not title:
                await message.answer("Nom bo'sh bo'lmasligi kerak. Qaytadan kiriting:")
                return
            await state.update_data(title=title)
            await state.set_state(KinoStates.waiting_category)

            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="kino_skip_category"))
            builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="kino_cancel"))
            await message.answer(
                "Kategoriyasini kiriting (masalan: Jangari, Komediya) yoki o'tkazib yuboring:",
                reply_markup=builder.as_markup(),
            )

        async def _after_category(state: FSMContext) -> tuple[str, object]:
            """Kategoriyadan keyingi qadamni aniqlaydi — agar Premium obuna
            yoqilgan bo'lsa, avval "oddiymi yoki premiummi" so'raladi."""
            if bot_row.premium_subscription_enabled:
                await state.set_state(KinoStates.waiting_premium_choice)
                kb = InlineKeyboardBuilder()
                kb.button(text="🆓 Oddiy", callback_data="kino_premium_no")
                kb.button(text="⭐ Premium", callback_data="kino_premium_yes")
                kb.adjust(2)
                return "Bu kino oddiymi yoki Premium obunachilar uchunmi?", kb.as_markup()
            await state.update_data(is_premium=False)
            await state.set_state(KinoStates.waiting_media)
            return "Endi kino faylini (video yoki hujjat) yuboring:", _cancel_keyboard().as_markup()

        @router.callback_query(KinoStates.waiting_category, F.data == "kino_skip_category")
        async def on_category_skip(callback: CallbackQuery, state: FSMContext) -> None:
            await state.update_data(category=None)
            text, kb = await _after_category(state)
            await callback.answer()
            await callback.message.answer(text, reply_markup=kb)

        @router.message(KinoStates.waiting_category)
        async def on_category_entered(message: Message, state: FSMContext) -> None:
            category = (message.text or "").strip() or None
            await state.update_data(category=category)
            text, kb = await _after_category(state)
            await message.answer(text, reply_markup=kb)

        @router.callback_query(KinoStates.waiting_premium_choice, F.data.in_({"kino_premium_no", "kino_premium_yes"}))
        async def on_premium_choice(callback: CallbackQuery, state: FSMContext) -> None:
            is_premium = callback.data == "kino_premium_yes"
            await state.update_data(is_premium=is_premium)
            await state.set_state(KinoStates.waiting_media)
            await callback.answer()
            await callback.message.answer(
                "Endi kino faylini (video yoki hujjat) yuboring:", reply_markup=_cancel_keyboard().as_markup()
            )

        @router.message(KinoStates.waiting_media, F.video | F.document)
        async def on_media_received(message: Message, state: FSMContext, session: AsyncSession) -> None:
            data = await state.get_data()

            if message.video:
                file_type, file_id = "video", message.video.file_id
            else:
                file_type, file_id = "document", message.document.file_id

            try:
                await check_and_increment_feature_limit(
                    session, bot_row.id, KINO_QOSHISH_FEATURE_KEY, KINO_QOSHISH_DAILY_LIMIT
                )
            except LimitExceededError:
                await state.clear()
                await message.answer(
                    f"⛔ Bugungi kunlik kino qo'shish limitingiz tugadi ({KINO_QOSHISH_DAILY_LIMIT}/kun).\n"
                    "Ertaga qayta urinib ko'ring."
                )
                return

            movie = Movie(
                bot_id=bot_row.id,
                code=data["code"],
                title=data["title"],
                category=data.get("category"),
                file_type=file_type,
                file_id=file_id,
                views=0,
                is_premium=data.get("is_premium", False),
            )
            session.add(movie)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await state.clear()
                await message.answer(
                    "⚠️ Bu kod ayni shu paytda band bo'lib qoldi (ehtimol tasodifiy takror urinish). "
                    "Iltimos /kino_qoshish bilan qaytadan boshqa kod bilan urinib ko'ring."
                )
                return

            await state.clear()
            await message.answer(f"✅ Kino qo'shildi!\n\n{_movie_caption(movie)}")

        @router.message(KinoStates.waiting_media)
        async def on_media_wrong_type(message: Message) -> None:
            await message.answer(
                "Iltimos, video yoki hujjat (fayl) ko'rinishida yuboring, yoki /bekor bilan to'xtating."
            )

        # ---------------------------------------------------------------
        # Bot egasi uchun: kino o'chirish (buyruq orqali — tasdiqlash bilan)
        # ---------------------------------------------------------------

        @router.message(Command("kino_ochirish"))
        async def cmd_delete_movie(message: Message, command: CommandObject, session: AsyncSession) -> None:
            if not await is_bot_owner_or_sub_admin(session, bot_row.id, message.from_user.id):
                await message.answer("⛔ Bu buyruq faqat bot egasi uchun.")
                return

            code = (command.args or "").strip()
            if not code:
                await message.answer("Kodni ko'rsating: /kino_ochirish <kod>")
                return

            result = await session.execute(
                select(Movie).where(Movie.bot_id == bot_row.id, Movie.code == code)
            )
            movie = result.scalar_one_or_none()
            if movie is None:
                await message.answer("Bunday kod topilmadi.")
                return

            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"kino_admin_del_do:{code}"))
            builder.row(InlineKeyboardButton(text="↩️ Bekor", callback_data="kino_cancel"))
            await message.answer(
                f"«{movie.title}» (kod: {code}) rostdan o'chirilsinmi? Bu amalni qaytarib bo'lmaydi.",
                reply_markup=builder.as_markup(),
            )

        # ---------------------------------------------------------------
        # Premium obuna tizimi — bot egasi uchun sozlash
        # ---------------------------------------------------------------

        @router.message(Command("premium_narx"))
        async def cmd_premium_price_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
            if not await is_bot_owner(session, bot_row.id, message.from_user.id):
                await message.answer("⛔ Bu buyruq faqat bot egasi uchun.")
                return
            await state.clear()
            await state.set_state(PremiumStates.waiting_for_price)
            await message.answer(
                f"Joriy narx: {int(bot_row.premium_subscription_price)} so'm "
                f"({'yoqilgan' if bot_row.premium_subscription_enabled else 'o\u2019chirilgan'}).\n\n"
                "Yangi narxni so'mda kiriting (0 = Premium obunani butunlay o'chirish):"
            )

        @router.message(PremiumStates.waiting_for_price)
        async def on_premium_price_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
            raw = (message.text or "").strip()
            if not raw.isdigit():
                await message.answer("Iltimos, son kiriting (masalan: 15000 yoki 0):")
                return

            price = int(raw)
            if price == 0:
                try:
                    await check_and_increment_edit_limit(session, bot_row.id)
                except LimitExceededError as exc:
                    await state.clear()
                    await message.answer(f"⛔ Kunlik tahrirlash limitiga yetdingiz: {exc}")
                    return

                await set_premium_settings(session, bot_row.id, enabled=False, price=0, duration_days=bot_row.premium_subscription_duration_days)
                bot_row.premium_subscription_enabled = False
                bot_row.premium_subscription_price = 0
                await state.clear()
                await message.answer("✅ Premium obuna o'chirildi.")
                return

            await state.update_data(price=price)
            await state.set_state(PremiumStates.waiting_for_duration)
            await message.answer(
                f"Necha kunga (odatiy: {bot_row.premium_subscription_duration_days})? "
                "Son kiriting yoki /otkazish bilan odatiyni qoldiring:"
            )

        @router.message(PremiumStates.waiting_for_duration, Command("otkazish"))
        async def on_premium_duration_default(message: Message, state: FSMContext, session: AsyncSession) -> None:
            await _finish_premium_settings(message, state, session, bot_row.premium_subscription_duration_days)

        @router.message(PremiumStates.waiting_for_duration)
        async def on_premium_duration_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
            raw = (message.text or "").strip()
            if not raw.isdigit() or int(raw) <= 0:
                await message.answer("Iltimos, musbat son kiriting (masalan: 30), yoki /otkazish:")
                return
            await _finish_premium_settings(message, state, session, int(raw))

        async def _finish_premium_settings(
            message: Message, state: FSMContext, session: AsyncSession, duration_days: int
        ) -> None:
            try:
                await check_and_increment_edit_limit(session, bot_row.id)
            except LimitExceededError as exc:
                await state.clear()
                await message.answer(f"⛔ Kunlik tahrirlash limitiga yetdingiz: {exc}")
                return

            data = await state.get_data()
            price = data.get("price", 0)
            updated = await set_premium_settings(session, bot_row.id, enabled=True, price=price, duration_days=duration_days)
            bot_row.premium_subscription_enabled = updated.premium_subscription_enabled
            bot_row.premium_subscription_price = updated.premium_subscription_price
            bot_row.premium_subscription_duration_days = updated.premium_subscription_duration_days

            await state.clear()
            await message.answer(
                f"✅ Premium obuna yoqildi: {price} so'm / {duration_days} kun.\n\n"
                "Kino qo'shishda endi \"Oddiy yoki Premium\" so'raladi."
            )

        # ---------------------------------------------------------------
        # Premium obuna tizimi — oddiy foydalanuvchi uchun obuna bo'lish
        # ---------------------------------------------------------------

        @router.message(Command("premium"))
        async def cmd_premium_subscribe(message: Message, state: FSMContext, session: AsyncSession) -> None:
            if not bot_row.premium_subscription_enabled:
                await message.answer("Bu botda Premium obuna tizimi hozircha yoqilmagan.")
                return

            expiry = await get_premium_expiry(session, bot_row.id, message.from_user.id)
            if expiry and expiry >= datetime.date.today():
                await message.answer(f"✅ Sizda allaqachon faol Premium obuna bor — {expiry.strftime('%Y-%m-%d')} gacha.")
                return

            await state.clear()
            await state.set_state(PremiumStates.waiting_for_receipt)
            await message.answer(
                f"⭐ Premium obuna narxi: {int(bot_row.premium_subscription_price)} so'm "
                f"({bot_row.premium_subscription_duration_days} kunga).\n\n"
                "To'lov chekining skrinshotini shu yerga RASM qilib yuboring."
            )

        @router.message(PremiumStates.waiting_for_receipt, F.photo)
        async def on_premium_receipt(message: Message, state: FSMContext, session: AsyncSession, bot: AiogramBot) -> None:
            await state.clear()
            file_id = message.photo[-1].file_id
            payment = await submit_premium_payment(
                session, bot_row.id, message.from_user.id, float(bot_row.premium_subscription_price), file_id
            )
            await message.answer("✅ Chekingiz qabul qilindi. Tasdiqlangach xabar beramiz.")

            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Tasdiqlash", callback_data=f"premium_approve:{payment.id}")
            kb.button(text="❌ Rad etish", callback_data=f"premium_reject:{payment.id}")
            kb.adjust(2)

            owner_result = await session.execute(select(User.telegram_id).where(User.id == bot_row.owner_id))
            owner_telegram_id = owner_result.scalar_one_or_none()
            if owner_telegram_id is None:
                logger.warning("Bot egasi topilmadi: bot_id=%s", bot_row.id)
                return
            try:
                await bot.send_photo(
                    owner_telegram_id,
                    file_id,
                    caption=(
                        f"⭐ Yangi Premium obuna cheki\n\n"
                        f"Foydalanuvchi: {message.from_user.full_name} (id: {message.from_user.id})\n"
                        f"Summa: {int(payment.amount)} so'm"
                    ),
                    reply_markup=kb.as_markup(),
                )
            except Exception:
                logger.exception("Premium chek haqida bot egasiga xabar yuborishda xato")

        @router.message(PremiumStates.waiting_for_receipt)
        async def on_premium_receipt_invalid(message: Message) -> None:
            await message.answer("Iltimos, chekning skrinshotini RASM ko'rinishida yuboring.")

        @router.callback_query(F.data.startswith("premium_approve:"))
        async def on_premium_approve(callback: CallbackQuery, session: AsyncSession, bot: AiogramBot) -> None:
            if not await is_bot_owner(session, bot_row.id, callback.from_user.id):
                await callback.answer("Bu amal faqat bot egasi uchun.", show_alert=True)
                return
            payment_id = int(callback.data.split(":", 1)[1])
            try:
                payment = await approve_premium_payment(session, payment_id)
            except PremiumPaymentNotFoundError:
                await callback.answer("To'lov topilmadi.", show_alert=True)
                return

            expiry = await get_premium_expiry(session, bot_row.id, payment.telegram_user_id)
            try:
                await bot.send_message(
                    payment.telegram_user_id,
                    f"✅ Premium obunangiz tasdiqlandi! Muddati: {expiry.strftime('%Y-%m-%d')} gacha.",
                )
            except Exception:
                logger.exception("Foydalanuvchiga premium tasdiqlash xabarini yuborishda xato")

            await callback.answer("Tasdiqlandi.")
            old_caption = callback.message.caption or ""
            await callback.message.edit_caption(caption=f"✅ TASDIQLANDI\n\n{old_caption}", reply_markup=None)

        @router.callback_query(F.data.startswith("premium_reject:"))
        async def on_premium_reject(callback: CallbackQuery, session: AsyncSession, bot: AiogramBot) -> None:
            if not await is_bot_owner(session, bot_row.id, callback.from_user.id):
                await callback.answer("Bu amal faqat bot egasi uchun.", show_alert=True)
                return
            payment_id = int(callback.data.split(":", 1)[1])
            try:
                payment = await reject_premium_payment(session, payment_id)
            except PremiumPaymentNotFoundError:
                await callback.answer("To'lov topilmadi.", show_alert=True)
                return

            try:
                await bot.send_message(
                    payment.telegram_user_id,
                    "❌ Premium obuna chekingiz rad etildi. Qaytadan yuborishingiz mumkin: /premium",
                )
            except Exception:
                logger.exception("Foydalanuvchiga premium rad etish xabarini yuborishda xato")

            await callback.answer("Rad etildi.")
            old_caption = callback.message.caption or ""
            await callback.message.edit_caption(caption=f"❌ RAD ETILDI\n\n{old_caption}", reply_markup=None)

        @router.message(Command("premium_tolovlar"))
        async def cmd_premium_pending(message: Message, session: AsyncSession) -> None:
            if not await is_bot_owner(session, bot_row.id, message.from_user.id):
                await message.answer("⛔ Bu buyruq faqat bot egasi uchun.")
                return
            pending = await list_pending_premium_payments(session, bot_row.id)
            if not pending:
                await message.answer("Kutilayotgan Premium to'lovlar yo'q.")
                return
            lines = ["⏳ Kutilayotgan Premium to'lovlar:\n"]
            for p in pending:
                lines.append(f"#{p.id} — foydalanuvchi {p.telegram_user_id} — {int(p.amount)} so'm")
            lines.append("\nHar birini tasdiqlash/rad etish uchun chekning o'zi yuborilgan xabarga qarang.")
            await message.answer("\n".join(lines))

        # ---------------------------------------------------------------
        # Fallback: oddiy matn — kino kodi sifatida qaraladi
        # ---------------------------------------------------------------

        @router.message(F.text)
        async def on_plain_text(message: Message, session: AsyncSession, bot: AiogramBot) -> None:
            code = (message.text or "").strip()
            found = await _send_movie_by_code(session, bot, message.chat.id, bot_row.id, code)
            if not found:
                await message.answer(
                    "😕 Bunday kodli kino topilmadi.\n"
                    "To'g'ri kodni yuboring yoki /qidir <nom> orqali qidiring."
                )

        # Core funksiyalar (captcha/welcome) avval ro'yxatdan o'tadi — aks holda
        # quyidagi modul routeridagi umumiy fallback handler ularni "yutib qo'yadi".
        self.register_core_features(dp)
        dp.include_router(router)


async def _start_add_flow(message: Message, state: FSMContext) -> None:
    await state.set_state(KinoStates.waiting_code)
    await message.answer(
        "Yangi kino uchun noyob kod kiriting (masalan: 1024):",
        reply_markup=_cancel_keyboard().as_markup(),
    )


async def _render_movie_list(callback: CallbackQuery, session: AsyncSession, bot_id: int, page: int) -> None:
    offset = page * PAGE_SIZE
    result = await session.execute(
        select(Movie).where(Movie.bot_id == bot_id).order_by(Movie.id.desc()).offset(offset).limit(PAGE_SIZE)
    )
    movies = result.scalars().all()

    count_result = await session.execute(select(func.count()).select_from(Movie).where(Movie.bot_id == bot_id))
    total = count_result.scalar_one()

    if not movies and page == 0:
        text = "Hozircha kinolar mavjud emas."
    else:
        lines = [f"📋 Kinolar ro'yxati ({total} ta):\n"]
        for movie in movies:
            lines.append(f"🔑 {movie.code} — {movie.title} (👁 {movie.views})")
        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"kino_admin_list:{page - 1}"))
    if offset + PAGE_SIZE < total:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"kino_admin_list:{page + 1}"))
    if nav_row:
        builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kino_admin_back"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


async def _render_delete_list(callback: CallbackQuery, session: AsyncSession, bot_id: int, page: int) -> None:
    offset = page * PAGE_SIZE
    result = await session.execute(
        select(Movie).where(Movie.bot_id == bot_id).order_by(Movie.id.desc()).offset(offset).limit(PAGE_SIZE)
    )
    movies = result.scalars().all()

    count_result = await session.execute(select(func.count()).select_from(Movie).where(Movie.bot_id == bot_id))
    total = count_result.scalar_one()

    builder = InlineKeyboardBuilder()

    if not movies and page == 0:
        builder.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kino_admin_back"))
        await callback.message.edit_text("Hozircha kinolar mavjud emas.", reply_markup=builder.as_markup())
        return

    for movie in movies:
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {movie.title} ({movie.code})", callback_data=f"kino_admin_del_confirm:{movie.code}"
            )
        )

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"kino_admin_delete:{page - 1}"))
    if offset + PAGE_SIZE < total:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"kino_admin_delete:{page + 1}"))
    if nav_row:
        builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="↩️ Orqaga", callback_data="kino_admin_back"))

    await callback.message.edit_text(f"🗑 O'chirish uchun tanlang ({total} ta):", reply_markup=builder.as_markup())


async def _send_movie_by_code(
    session: AsyncSession, bot: AiogramBot, chat_id: int, bot_id: int, code: str
) -> bool:
    """Kod bo'yicha kino topib yuboradi, ko'rishlar sonini +1 oshiradi. Topilsa True qaytaradi."""
    result = await session.execute(select(Movie).where(Movie.bot_id == bot_id, Movie.code == code))
    movie = result.scalar_one_or_none()
    if movie is None:
        return False

    if movie.is_premium and not await has_active_premium(session, bot_id, chat_id):
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"⭐ «{movie.title}» — Premium kino, faqat obunachilar ko'ra oladi.\n\n"
                "Obuna bo'lish uchun /premium yuboring."
            ),
        )
        return True

    # Atomik increment — parallel so'rovlarda hisoblagich yo'qolib qolmasligi uchun
    # (avval "views = views + 1" Python darajasida hisoblanardi, race condition xavfi bor edi).
    await session.execute(update(Movie).where(Movie.id == movie.id).values(views=Movie.views + 1))
    await session.commit()
    movie.views += 1  # caption uchun local obyektni ham yangilaymiz

    caption = _movie_caption(movie)
    try:
        if movie.file_type == "video":
            await bot.send_video(chat_id=chat_id, video=movie.file_id, caption=caption)
        else:
            await bot.send_document(chat_id=chat_id, document=movie.file_id, caption=caption)
    except TelegramBadRequest:
        # file_id eskirgan/yaroqsiz bo'lib qolgan bo'lishi mumkin (Telegram fayllarni
        # ba'zan serverdan tozalab yuboradi). Avval bu holatda foydalanuvchi hech qanday
        # javob olmasdi — endi aniq xabar beriladi.
        logger.warning("Fayl yuborib bo'lmadi (file_id yaroqsiz bo'lishi mumkin): code=%s", code)
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ «{movie.title}» fayli hozircha yuborilmadi. Bot egasiga xabar bering.",
        )
    return True
