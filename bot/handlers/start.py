"""/start — знакомство + главное меню."""

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from ..db import Request, SessionLocal, get_or_create_user
from ..keyboards import main_menu, reply_cancel
from ..states import Registration
from ..utils.text import h

router = Router(name="start")


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    tg_user = message.from_user
    if tg_user is None:
        return

    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg_user.id, tg_user.username)
        has_name = bool(user.name)

    if has_name:
        await message.answer(
            f"С возвращением, <b>{h(user.name)}</b>! 👋\n\n"
            "Выберите, что сделать:",
            reply_markup=main_menu(),
        )
        return

    await state.set_state(Registration.waiting_for_name)
    await message.answer(
        "👋 Привет! Я <b>era_etp_bot</b> — помогу подобрать автомобиль, "
        "запчасти или выполнить покупку под ключ.\n\n"
        "Как вас зовут?",
        reply_markup=reply_cancel(),
    )


@router.message(Registration.waiting_for_name, F.text)
async def on_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 64:
        await message.answer("Пожалуйста, введите имя от 2 до 64 символов.")
        return
    tg_user = message.from_user
    if tg_user is None:
        return
    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg_user.id, tg_user.username)
        user.name = name
        await session.commit()
    await state.clear()
    await message.answer(
        f"Приятно познакомиться, <b>{h(name)}</b>! Выберите, что сделать:",
        reply_markup=main_menu(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("📍 Главное меню", reply_markup=main_menu())


@router.callback_query(F.data == "menu:home")
async def cb_menu_home(cb: CallbackQuery) -> None:
    if cb.message:
        await cb.message.answer("📍 Главное меню", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data == "menu:my")
async def cb_my_requests(cb: CallbackQuery) -> None:
    tg = cb.from_user
    async with SessionLocal() as session:
        res = await session.execute(
            select(Request)
            .join(Request.user)
            .where(Request.user.has(tg_id=tg.id))
            .order_by(Request.created_at.desc())
            .limit(20)
        )
        rows = res.scalars().all()

    if not rows:
        text = "У вас пока нет заявок. Выберите раздел в меню, чтобы оформить первую."
    else:
        lines: list[str] = ["<b>Ваши заявки (последние 20):</b>\n"]
        kind_ru = {"car": "🚗 Авто", "parts": "🔧 Запчасти", "shop": "🛒 Покупка"}
        for r in rows:
            dt = r.created_at.strftime("%d.%m.%Y %H:%M")
            payload = json.loads(r.payload_json)
            summary = payload.get("summary") or payload.get("brand") or "заявка"
            lines.append(
                f"• #{r.id} | {dt} | {kind_ru.get(r.kind, r.kind)} | "
                f"<i>{h(summary)}</i> | статус: {h(r.status)}"
            )
        text = "\n".join(lines)

    if cb.message:
        await cb.message.edit_text(text, reply_markup=main_menu())
    await cb.answer()
