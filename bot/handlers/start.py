"""/start — знакомство + главное меню."""

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from ..db import Request, SessionLocal, get_or_create_user
from ..keyboards import WELCOME_BUTTON_TEXT, main_menu, reply_cancel, welcome_reply_kb
from ..states import Registration
from ..utils.text import h

router = Router(name="start")


WELCOME_BANNER = (
    "🌐 <b>ERA</b> — ваш личный шопинг-агент за рубежом.\n\n"
    "Amazon, ASOS, iHerb, официальные сайты брендов — мы выкупим и доставим "
    "всё, что вы найдёте в интернете.\n\n"
    "Оплачивайте привычной российской картой через СБП 💳\n\n"
    "Нашли нужный товар? Оставляйте заявку — остальное за нами ✈️"
)


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    """`/start` показывает только одно: full-width reply-кнопку «🚀 Начать».

    Никакого баннера/меню здесь — иначе следом отправляемое сообщение с
    inline-меню в большинстве Telegram-клиентов схлопывает reply-клавиатуру
    под иконку команд бота, и кнопка перестаёт быть видна. Сам welcome-flow
    (баннер + меню или анкета имени) поднимается уже из ``on_welcome_button``
    после явного тапа.
    """
    await state.clear()
    tg_user = message.from_user
    if tg_user is None:
        return

    async with SessionLocal() as session:
        # Создаём запись пользователя, чтобы при тапе по «🚀 Начать»
        # сразу знать, новичок он или возвращающийся.
        await get_or_create_user(session, tg_user.id, tg_user.username)

    await message.answer(
        "👇 Нажми кнопку, чтобы начать.",
        reply_markup=welcome_reply_kb(),
    )


async def _send_welcome_flow(message: Message, state: FSMContext) -> None:
    """Общий welcome-flow: баннер + (главное меню | анкета имени).

    Вызывается и из ``on_welcome_button`` (тап по «🚀 Начать»), и при
    необходимости из других мест. Здесь и приходит «здарова» от бота —
    после явного действия пользователя, а не на сухой ``/start``.
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg_user.id, tg_user.username)
        has_name = bool(user.name)

    # Баннер шлём всегда: и новичкам, и возвращающимся. Без reply_markup,
    # чтобы reply-клавиатура «🚀 Начать», поднятая из /start, осталась
    # развёрнутой над полем ввода.
    await message.answer(WELCOME_BANNER)

    if has_name:
        await message.answer(
            f"С возвращением, <b>{h(user.name)}</b>! Выбери раздел:",
            reply_markup=main_menu(),
        )
        return

    # Новый пользователь — переходим в регистрацию (имя).
    await state.set_state(Registration.waiting_for_name)
    await message.answer(
        "Для начала — как тебя зовут?",
        reply_markup=reply_cancel(),
    )


@router.message(Registration.waiting_for_name, F.text)
async def on_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if name == WELCOME_BUTTON_TEXT:
        # Защита: если юзер во время анкеты тапнул по «🚀 Начать»,
        # не воспринимаем это как имя.
        await message.answer(
            "Введи, пожалуйста, своё имя текстом.",
            reply_markup=reply_cancel(),
        )
        return
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
    # Возвращаем persistent reply-клавиатуру с «🚀 Начать» (анкета затёрла
    # её клавиатурой «Отмена») + показываем главное меню.
    await message.answer(
        f"Приятно познакомиться, <b>{h(name)}</b>!",
        reply_markup=welcome_reply_kb(),
    )
    await message.answer(
        "Выбери раздел:",
        reply_markup=main_menu(),
    )


@router.message(F.text == WELCOME_BUTTON_TEXT)
async def on_welcome_button(message: Message, state: FSMContext) -> None:
    """Тап по reply-кнопке «🚀 Начать» — основная точка входа в бот."""
    await state.clear()
    await _send_welcome_flow(message, state)


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
