"""
module_type -> Modul klassi xaritasi (TZ 4.7-bo'lim: "plagin" tamoyili).

Yangi modul turi qo'shish uchun faqat shu yerga bitta qator qo'shiladi —
core dispatcher yoki boshqa modullarga tegilmaydi.
"""
from __future__ import annotations

from app.models.base import ModuleType
from app.modules.admin.module import AdminModule
from app.modules.base import BaseModule
from app.modules.custom.module import CustomModule
from app.modules.game.module import GameModule
from app.modules.kino.module import KinoModule
from app.modules.shop.module import ShopModule
from app.modules.support.module import SupportModule

_MODULE_MAP: dict[ModuleType, type[BaseModule]] = {
    ModuleType.ADMIN: AdminModule,
    ModuleType.SUPPORT: SupportModule,
    ModuleType.KINO: KinoModule,
    ModuleType.SHOP: ShopModule,
    ModuleType.GAME_GOT: GameModule,
    ModuleType.GAME_MAFIA: GameModule,
    ModuleType.GAME_BUNKER: GameModule,
    ModuleType.CUSTOM: CustomModule,
}


def get_module_class(module_type: ModuleType) -> type[BaseModule]:
    try:
        return _MODULE_MAP[module_type]
    except KeyError as exc:
        raise ValueError(f"Noma'lum module_type: {module_type}") from exc
