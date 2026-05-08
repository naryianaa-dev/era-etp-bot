"""Роутеры бота."""

from aiogram import Router

from . import admin, car, common, parts, shop, start


def get_main_router() -> Router:
    router = Router(name="root")
    # порядок важен: /cancel /back должен ловиться раньше остальных
    router.include_router(common.router)
    router.include_router(start.router)
    router.include_router(admin.router)
    router.include_router(car.router)
    router.include_router(parts.router)
    router.include_router(shop.router)
    return router
