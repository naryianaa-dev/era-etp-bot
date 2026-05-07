"""Ветка «Запчасти»."""

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import Request, SessionLocal, get_or_create_user
from ..keyboards import main_menu, reply_cancel, yes_no_kb
from ..notify import notify_admins_new_request
from ..states import PartsFlow
from ..utils.validators import is_valid_vin, parse_year

router = Router(name="parts")


@router.callback_query(F.data == "menu:parts")
async def cb_enter_parts(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PartsFlow.brand)
    if cb.message:
        await cb.message.edit_text(
            "🔧 <b>Запчасти</b>\n\nМарка автомобиля:"
        )
        await cb.message.answer("Для отмены нажмите «Отмена».", reply_markup=reply_cancel())
    await cb.answer()


@router.message(PartsFlow.brand, F.text)
async def on_brand(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if not (1 <= len(val) <= 32):
        await message.answer("Марка 1-32 символа.")
        return
    await state.update_data(brand=val)
    await state.set_state(PartsFlow.model)
    await message.answer("Модель:")


@router.message(PartsFlow.model, F.text)
async def on_model(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if not (1 <= len(val) <= 64):
        await message.answer("Модель 1-64 символа.")
        return
    await state.update_data(model=val)
    await state.set_state(PartsFlow.year)
    await message.answer("Год выпуска (целое число, например 2018):")


@router.message(PartsFlow.year, F.text)
async def on_year(message: Message, state: FSMContext) -> None:
    year = parse_year(message.text or "")
    if year is None:
        await message.answer("Год должен быть целым числом от 1950 до сейчас.")
        return
    await state.update_data(year=year)
    await state.set_state(PartsFlow.vin)
    await message.answer("VIN-номер (17 символов, латиница + цифры). Если VIN нет — напишите «нет»:")


@router.message(PartsFlow.vin, F.text)
async def on_vin(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw.lower() in ("нет", "no", "-", "—"):
        vin = None
    elif is_valid_vin(raw):
        vin = raw.upper().replace(" ", "")
    else:
        await message.answer(
            "VIN невалидный. Должно быть 11-17 символов (латиница A-H, J-N, P, R-Z и цифры) без I, O, Q.\n"
            "Пример: <code>WBADT43452G025250</code>. Или напишите «нет»."
        )
        return
    await state.update_data(vin=vin)
    await state.set_state(PartsFlow.part_name)
    await message.answer("Название детали (что нужно):")


@router.message(PartsFlow.part_name, F.text)
async def on_part_name(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if not (1 <= len(val) <= 128):
        await message.answer("Название 1-128 символов.")
        return
    await state.update_data(part_name=val)
    await state.set_state(PartsFlow.has_part_number)
    await message.answer(
        "Знаете артикул (партномер) детали?",
        reply_markup=yes_no_kb("parts_art"),
    )


@router.callback_query(PartsFlow.has_part_number, F.data.startswith("parts_art:"))
async def on_has_art(cb: CallbackQuery, state: FSMContext) -> None:
    choice = (cb.data or "").rsplit(":", 1)[-1]
    if choice == "yes":
        await state.set_state(PartsFlow.part_number)
        if cb.message:
            await cb.message.edit_text("Введите артикул:")
        await cb.answer()
        return
    # нет артикула → проверяем фото
    await state.update_data(part_number=None)
    await state.set_state(PartsFlow.has_photo)
    if cb.message:
        await cb.message.edit_text(
            "Артикула нет. Можете прислать фото детали?",
            reply_markup=yes_no_kb("parts_photo"),
        )
    await cb.answer()


@router.message(PartsFlow.part_number, F.text)
async def on_part_number(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if not (2 <= len(val) <= 64):
        await message.answer("Артикул 2-64 символа.")
        return
    await state.update_data(part_number=val)
    await _finalize_parts(message, state)


@router.callback_query(PartsFlow.has_photo, F.data.startswith("parts_photo:"))
async def on_has_photo(cb: CallbackQuery, state: FSMContext) -> None:
    choice = (cb.data or "").rsplit(":", 1)[-1]
    if choice == "yes":
        await state.set_state(PartsFlow.photo)
        if cb.message:
            await cb.message.edit_text("Пришлите фото детали одним сообщением:")
        await cb.answer()
        return
    await state.update_data(photo_file_id=None)
    if cb.message:
        await _finalize_parts_cb(cb, state)


@router.message(PartsFlow.photo, F.photo)
async def on_photo(message: Message, state: FSMContext) -> None:
    # самое большое из присланных фото
    photo = message.photo[-1] if message.photo else None
    if photo is None:
        await message.answer("Не вижу фото. Пришлите картинкой.")
        return
    await state.update_data(photo_file_id=photo.file_id)
    await _finalize_parts(message, state)


@router.message(PartsFlow.photo)
async def on_photo_wrong(message: Message) -> None:
    await message.answer("Нужно именно фото (картинкой), а не файл/текст.")


async def _finalize_parts(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tg = message.from_user
    summary = (
        f"{data.get('brand')} {data.get('model')} {data.get('year')}: {data.get('part_name')}"
    )
    payload = {
        "brand": data.get("brand"),
        "model": data.get("model"),
        "year": data.get("year"),
        "vin": data.get("vin"),
        "part_name": data.get("part_name"),
        "part_number": data.get("part_number"),
        "photo_file_id": data.get("photo_file_id"),
        "summary": summary,
    }
    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg.id, tg.username)
        req = Request(
            user_id=user.id, kind="parts",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
        if message.bot is not None:
            await notify_admins_new_request(message.bot, req, user)
    await state.clear()
    await message.answer(
        f"✅ <b>Заявка #{req.id} на запчасть принята.</b>\n\n"
        f"{summary}\n"
        + (f"VIN: <code>{data.get('vin')}</code>\n" if data.get("vin") else "")
        + (f"Артикул: <code>{data.get('part_number')}</code>\n" if data.get("part_number") else "")
        + ("Фото: получено\n" if data.get("photo_file_id") else "")
        + "\nМенеджер подберёт деталь и свяжется с вами.",
        reply_markup=main_menu(),
    )


async def _finalize_parts_cb(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    tg = cb.from_user
    summary = (
        f"{data.get('brand')} {data.get('model')} {data.get('year')}: {data.get('part_name')}"
    )
    payload = {
        "brand": data.get("brand"),
        "model": data.get("model"),
        "year": data.get("year"),
        "vin": data.get("vin"),
        "part_name": data.get("part_name"),
        "part_number": data.get("part_number"),
        "photo_file_id": data.get("photo_file_id"),
        "summary": summary,
    }
    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg.id, tg.username)
        req = Request(
            user_id=user.id, kind="parts",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
        if cb.bot is not None:
            await notify_admins_new_request(cb.bot, req, user)
    await state.clear()
    text = (
        f"✅ <b>Заявка #{req.id} на запчасть принята.</b>\n\n{summary}\n\n"
        "Менеджер подберёт деталь и свяжется с вами."
    )
    if cb.message:
        await cb.message.edit_text(text, reply_markup=main_menu())
    await cb.answer("Заявка отправлена")
