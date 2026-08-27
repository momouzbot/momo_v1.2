"""
GameModule — TZ 4.5-bo'lim.
Bitta klass uch xil module_type'ni (game_got, game_mafia, game_bunker)
xizmat qiladi, chunki ular umumiy GameCore komponentlaridan foydalanadi
(session_manager, role_distributor, voting_system, timer_engine).

Amalga oshirish tartibi (TZ 10-bo'lim, 8-qadam): avval Mafia yoki Bunker
(qisqa sessiya, soddaroq), keyin GOT Game (MVP).
"""
from __future__ import annotations

from aiogram import Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.models.base import ModuleType
from app.modules.base import BaseModule


class GameModule(BaseModule):
    def register_handlers(self, dp: Dispatcher) -> None:
        router = Router(name=f"game_{self.bot_row.id}")
        game_type = ModuleType(self.bot_row.module_type)

        @router.message(CommandStart())
        async def cmd_start(message: Message) -> None:
            names = {
                ModuleType.GAME_GOT: "GOT Game",
                ModuleType.GAME_MAFIA: "Mafia",
                ModuleType.GAME_BUNKER: "Bunker",
            }
            await message.answer(f"{names[game_type]} bot ishga tushdi. /join — o'yinga qo'shilish.")

        # TODO: GameCore orqali session_manager/role_distributor/voting_system/
        # timer_engine ulash; game_settings jadvalidagi cheklovlarni tekshirish
        # (max_players, max_active_sessions) — TZ 4.5.4

        # Core funksiyalar (captcha/welcome) avval ro'yxatdan o'tadi — aks holda
        # quyidagi modul routeridagi umumiy fallback handler ularni "yutib qo'yadi".
        self.register_core_features(dp)
        dp.include_router(router)
