"""
KinoBotModule (`kino`) — TZ 4.3-bo'lim, to'liq amalga oshirilgan versiya.

Foydalanuvchi uchun:
    /start        — xush kelibsiz + yo'riqnoma
    <kod>         — kino kodini yuborsa, mos kino topilib yuboriladi
    /qidir <nom>  — nom bo'yicha qidiruv (inline natijalar ro'yxati)
    /top          — eng ko'p ko'rilgan 10 ta kino

Bot egasi uchun (faqat owner_telegram_id mos kelsa):
    /kino_qoshish   — FSM orqali yangi kino qo'shish (kod → nom → kategoriya → media)
    /kino_ochirish <kod> — kinoni o'chirish
"""
from __future__ import annotations

import logging

from aiogram import Bot as AiogramBot
from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.movie import Movie
from app.modules.base import BaseModule
from app.services.ownership import is_bot_owner

logger = logging.getLogger(__name__)


class KinoStates(StatesGroup):
    waiting_code = State()
    waiting_title = State()
    waiting_category = State()
    waiting_media = State()


def _movie_caption(movie: Movie) -> str:
    category = f"\n🏷 Kategoriya: {movie.category}" if movie.category else ""
    return f"🎬 {movie.title}{category}\n🔑 Kod: {movie.code}\n👁 Ko'rishlar: {movie.views}"


class KinoModule(BaseModule):
    def register_handlers(self, dp: Dispatcher) -> None:
        router = Router(name=f"kino_{self.bot_row.id}")
        bot_row = self.bot_row

        # ---------------------------------------------------------------
        # Foydalanuvchi buyruqlari
        # ---------------------------------------------------------------

        @router.message(CommandStart())
        async def cmd_start(message: Message) -> None:
            await message.answer(
                "🎬 Kino-botga xush kelibsiz!\n\n"
                "Kino kodini yuboring — men sizga filmni topib beraman.\n"
                "Nom bo'yicha qidirish uchun: /qidir <nom>\n"
                "Top-10 kinolarni ko'rish: /top"
            )

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
                .where(Movie.bot_id == bot_row.id, Movie.title.ilike(f"%{query}%"))
                .order_by(Movie.views.desc())
                .limit(10)
            )
            movies = result.scalars().all()

            if not movies:
                await message.answer("Hech narsa topilmadi. Boshqa nom bilan urinib ko'ring.")
                return

            builder = InlineKeyboardBuilder()
            for movie in movies:
                builder.button(text=f"{movie.title} ({movie.code})", callback_data=f"kino_get:{movie.code}")
            builder.adjust(1)
            await message.answer("🔍 Natijalar:", reply_markup=builder.as_markup())

        @router.callback_query(F.data.startswith("kino_get:"))
        async def on_result_click(callback: CallbackQuery, session: AsyncSession, bot: AiogramBot) -> None:
            code = callback.data.split(":", 1)[1]
            await _send_movie_by_code(session, bot, callback.message.chat.id, bot_row.id, code)
            await callback.answer()

        # ---------------------------------------------------------------
        # Bot egasi uchun: kino qo'shish (FSM)
        # ---------------------------------------------------------------

        @router.message(Command("kino_qoshish"))
        async def cmd_add_movie_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
            if not await is_bot_owner(session, bot_row.id, message.from_user.id):
                await message.answer("⛔ Bu buyruq faqat bot egasi uchun.")
                return
            await state.set_state(KinoStates.waiting_code)
            await message.answer("Yangi kino uchun noyob kod kiriting (masalan: 1024):")

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
            await message.answer("Kino nomini kiriting:")

        @router.message(KinoStates.waiting_title)
        async def on_title_entered(message: Message, state: FSMContext) -> None:
            title = (message.text or "").strip()
            if not title:
                await message.answer("Nom bo'sh bo'lmasligi kerak. Qaytadan kiriting:")
                return
            await state.update_data(title=title)
            await state.set_state(KinoStates.waiting_category)

            builder = InlineKeyboardBuilder()
            builder.button(text="⏭ O'tkazib yuborish", callback_data="kino_skip_category")
            await message.answer(
                "Kategoriyasini kiriting (masalan: Jangari, Komediya) yoki o'tkazib yuboring:",
                reply_markup=builder.as_markup(),
            )

        @router.callback_query(KinoStates.waiting_category, F.data == "kino_skip_category")
        async def on_category_skip(callback: CallbackQuery, state: FSMContext) -> None:
            await state.update_data(category=None)
            await state.set_state(KinoStates.waiting_media)
            await callback.answer()
            await callback.message.answer("Endi kino faylini (video yoki hujjat) yuboring:")

        @router.message(KinoStates.waiting_category)
        async def on_category_entered(message: Message, state: FSMContext) -> None:
            category = (message.text or "").strip() or None
            await state.update_data(category=category)
            await state.set_state(KinoStates.waiting_media)
            await message.answer("Endi kino faylini (video yoki hujjat) yuboring:")

        @router.message(KinoStates.waiting_media, F.video | F.document)
        async def on_media_received(message: Message, state: FSMContext, session: AsyncSession) -> None:
            data = await state.get_data()

            if message.video:
                file_type, file_id = "video", message.video.file_id
            else:
                file_type, file_id = "document", message.document.file_id

            movie = Movie(
                bot_id=bot_row.id,
                code=data["code"],
                title=data["title"],
                category=data.get("category"),
                file_type=file_type,
                file_id=file_id,
                views=0,
            )
            session.add(movie)
            await session.commit()
            await state.clear()

            await message.answer(f"✅ Kino qo'shildi!\n\n{_movie_caption(movie)}")

        @router.message(KinoStates.waiting_media)
        async def on_media_wrong_type(message: Message) -> None:
            await message.answer("Iltimos, video yoki hujjat (fayl) ko'rinishida yuboring.")

        # ---------------------------------------------------------------
        # Bot egasi uchun: kino o'chirish
        # ---------------------------------------------------------------

        @router.message(Command("kino_ochirish"))
        async def cmd_delete_movie(message: Message, command: CommandObject, session: AsyncSession) -> None:
            if not await is_bot_owner(session, bot_row.id, message.from_user.id):
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

            await session.delete(movie)
            await session.commit()
            await message.answer(f"🗑 «{movie.title}» (kod: {code}) o'chirildi.")

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


async def _send_movie_by_code(
    session: AsyncSession, bot: AiogramBot, chat_id: int, bot_id: int, code: str
) -> bool:
    """Kod bo'yicha kino topib yuboradi, ko'rishlar sonini +1 oshiradi. Topilsa True qaytaradi."""
    result = await session.execute(select(Movie).where(Movie.bot_id == bot_id, Movie.code == code))
    movie = result.scalar_one_or_none()
    if movie is None:
        return False

    movie.views = movie.views + 1
    await session.commit()

    caption = _movie_caption(movie)
    if movie.file_type == "video":
        await bot.send_video(chat_id=chat_id, video=movie.file_id, caption=caption)
    else:
        await bot.send_document(chat_id=chat_id, document=movie.file_id, caption=caption)
    return True
