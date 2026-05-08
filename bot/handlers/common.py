"""Общие хендлеры: /cancel, /back, универсальные кнопки «Отмена»/«Назад»."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from ..keyboards import main_menu

router = Router(name="common")


@router.message(Command("cancel"))
@router.message(F.text.in_({"✖️ Отмена", "Отмена", "/cancel"}))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Действие отменено. Выберите, что сделать дальше:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("📍 Главное меню", reply_markup=main_menu())


@router.callback_query(F.data == "nav:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if cb.message:
        await cb.message.edit_text("Действие отменено.\n\n📍 Главное меню", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data == "nav:back")
async def cb_back(cb: CallbackQuery, state: FSMContext) -> None:
    """Базовый «Назад»: просто возвращаем в главное меню.

    В каждой ветке можно переопределить поведение, регистрируя свой cb
    раньше этого (например, car_back, parts_back). Сейчас — просто сброс.
    """
    await state.clear()
    if cb.message:
        await cb.message.edit_text("📍 Главное меню", reply_markup=main_menu())
    await cb.answer()


@router.message(F.text == "↩️ Назад")
async def back_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Вернулись в главное меню.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("📍 Главное меню", reply_markup=main_menu())
