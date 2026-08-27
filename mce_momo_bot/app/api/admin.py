"""
Admin panel API — TZ 8-bo'lim (Momo Admin roli) + foydalanuvchi so'rovi bo'yicha
modullarni yoqish/o'chirish funksiyasi.

    GET  /api/admin/modules                 — barcha modullar ro'yxati va holati
    POST /api/admin/modules/{code}/toggle    — modulni yoqish/o'chirish
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.base import ModuleType
from app.models.user import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ModuleResponse(BaseModel):
    code: ModuleType
    name: str
    description: str | None
    is_active: bool


class ToggleModuleRequest(BaseModel):
    is_active: bool
    requested_by_telegram_id: int


async def _require_momo_admin(session, telegram_id: int) -> None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_momo_admin:
        raise HTTPException(status_code=403, detail="Faqat Momo Admin bu amalni bajara oladi.")


@router.get("/modules", response_model=list[ModuleResponse])
async def list_modules_endpoint(requested_by_telegram_id: int = Query(...)) -> list[ModuleResponse]:
    async with AsyncSessionLocal() as session:
        await _require_momo_admin(session, requested_by_telegram_id)

        from app.services.modules import list_modules

        modules = await list_modules(session)
        return [
            ModuleResponse(code=m.code, name=m.name, description=m.description, is_active=m.is_active)
            for m in modules
        ]


@router.post("/modules/{code}/toggle", response_model=ModuleResponse)
async def toggle_module(code: ModuleType, payload: ToggleModuleRequest) -> ModuleResponse:
    async with AsyncSessionLocal() as session:
        await _require_momo_admin(session, payload.requested_by_telegram_id)

        from app.services.modules import set_module_active

        try:
            module_row = await set_module_active(session, code, payload.is_active)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return ModuleResponse(
            code=module_row.code,
            name=module_row.name,
            description=module_row.description,
            is_active=module_row.is_active,
        )
