"""Ветка «Автомобиль»: дилер / аукцион."""

from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import Request, SessionLocal, get_or_create_user
from ..keyboards import (
    condition_kb,
    drive_type_kb,
    gearbox_kb,
    main_menu,
    payment_method_kb,
    reply_cancel,
)
from ..notify import notify_admins_new_request
from ..states import CarFlow
from ..utils.validators import parse_mileage, parse_money_usd, parse_year

router = Router(name="car")
log = logging.getLogger(__name__)


# ----- вход в ветку ----- #
@router.callback_query(F.data == "menu:car")
async def cb_enter_car(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CarFlow.brand)
    if cb.message:
        await cb.message.edit_text(
            "🚗 <b>Подбор автомобиля</b>\n\nВведите марку (например, «BMW», «Toyota»):"
        )
    if cb.message:
        await cb.message.answer("Для отмены нажмите «Отмена».", reply_markup=reply_cancel())
    await cb.answer()


# ----- марка ----- #
@router.message(CarFlow.brand, F.text)
async def on_brand(message: Message, state: FSMContext) -> None:
    brand = (message.text or "").strip()
    if len(brand) < 1 or len(brand) > 32:
        await message.answer("Марка должна быть от 1 до 32 символов. Попробуйте ещё раз.")
        return
    await state.update_data(brand=brand)
    await state.set_state(CarFlow.model)
    await message.answer(f"Марка: <b>{brand}</b>\n\nВведите модель (например, «X5», «Camry»):")


# ----- модель ----- #
@router.message(CarFlow.model, F.text)
async def on_model(message: Message, state: FSMContext) -> None:
    model = (message.text or "").strip()
    if len(model) < 1 or len(model) > 64:
        await message.answer("Модель должна быть от 1 до 64 символов.")
        return
    await state.update_data(model=model)
    await state.set_state(CarFlow.min_year)
    await message.answer(
        f"Модель: <b>{model}</b>\n\nМинимальный год выпуска (целое число, например 2018):"
    )


# ----- год ----- #
@router.message(CarFlow.min_year, F.text)
async def on_year(message: Message, state: FSMContext) -> None:
    year = parse_year(message.text or "")
    if year is None:
        await message.answer("Не понял год. Введите целое число от 1950 до сейчас. Пример: 2018")
        return
    await state.update_data(min_year=year)
    await state.set_state(CarFlow.drive_type)
    await message.answer(
        f"Мин. год: <b>{year}</b>\n\nВыберите привод:", reply_markup=drive_type_kb()
    )


# ----- привод ----- #
@router.callback_query(CarFlow.drive_type, F.data.startswith("car_drive:"))
async def on_drive(cb: CallbackQuery, state: FSMContext) -> None:
    code = (cb.data or "").split(":", 1)[1]
    await state.update_data(drive_type=code)
    await state.set_state(CarFlow.gearbox)
    if cb.message:
        await cb.message.edit_text(
            f"Привод: <b>{code}</b>\n\nВыберите коробку:", reply_markup=gearbox_kb()
        )
    await cb.answer()


# ----- коробка ----- #
@router.callback_query(CarFlow.gearbox, F.data.startswith("car_gb:"))
async def on_gb(cb: CallbackQuery, state: FSMContext) -> None:
    code = (cb.data or "").split(":", 1)[1]
    await state.update_data(gearbox=code)
    await state.set_state(CarFlow.max_mileage)
    if cb.message:
        await cb.message.edit_text(
            f"Коробка: <b>{code}</b>\n\nМаксимальный пробег, км (целое число):"
        )
    await cb.answer()


# ----- пробег ----- #
@router.message(CarFlow.max_mileage, F.text)
async def on_mileage(message: Message, state: FSMContext) -> None:
    mileage = parse_mileage(message.text or "")
    if mileage is None:
        await message.answer("Не понял пробег. Введите целое число км (0..2 000 000). Пример: 120000")
        return
    await state.update_data(max_mileage=mileage)
    await state.set_state(CarFlow.condition)
    await message.answer(
        f"Макс. пробег: <b>{mileage:,} км</b>".replace(",", " ")
        + "\n\nГде искать автомобиль?",
        reply_markup=condition_kb(),
    )


# ----- дилер/аукцион ----- #
@router.callback_query(CarFlow.condition, F.data.startswith("car_cond:"))
async def on_condition(cb: CallbackQuery, state: FSMContext) -> None:
    code = (cb.data or "").split(":", 1)[1]
    await state.update_data(condition=code)
    if code == "dealer":
        await state.set_state(CarFlow.dealer_payment)
        if cb.message:
            await cb.message.edit_text(
                "🏢 <b>Дилер</b>\n\nКак оплатить заявку?",
                reply_markup=payment_method_kb("car_dealer"),
            )
    else:
        await state.set_state(CarFlow.auction_damage)
        if cb.message:
            await cb.message.edit_text(
                "🧰 <b>Аукцион</b>\n\nОпишите повреждения (текстом, 1-3 предложения):"
            )
    await cb.answer()


# ===== DEALER ===== #
@router.callback_query(CarFlow.dealer_payment, F.data.startswith("car_dealer:pay:"))
async def dealer_pay(cb: CallbackQuery, state: FSMContext) -> None:
    method = (cb.data or "").rsplit(":", 1)[-1]
    await state.update_data(payment_method=method)
    await _finalize_car(cb, state)


# ===== AUCTION ===== #
@router.message(CarFlow.auction_damage, F.text)
async def on_damage(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 3 or len(text) > 1000:
        await message.answer("Описание должно быть от 3 до 1000 символов.")
        return
    await state.update_data(auction_damage=text)
    await state.set_state(CarFlow.auction_max_bid_usd)
    await message.answer(
        "Максимальная ставка, <b>USD</b> (целое число):"
    )


@router.message(CarFlow.auction_max_bid_usd, F.text)
async def on_max_bid(message: Message, state: FSMContext) -> None:
    bid = parse_money_usd(message.text or "")
    if bid is None:
        await message.answer("Ставку не понял. Введите целое число USD, например: 15000")
        return
    await state.update_data(auction_max_bid_usd=bid)
    await state.set_state(CarFlow.auction_payment)
    await message.answer(
        f"Макс. ставка: <b>{bid:,} $</b>".replace(",", " ")
        + "\n\nКак оплатить заявку?",
        reply_markup=payment_method_kb("car_auction"),
    )


@router.callback_query(CarFlow.auction_payment, F.data.startswith("car_auction:pay:"))
async def auction_pay(cb: CallbackQuery, state: FSMContext) -> None:
    method = (cb.data or "").rsplit(":", 1)[-1]
    await state.update_data(payment_method=method)
    await _finalize_car(cb, state)


# ----- завершение ----- #
async def _finalize_car(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    tg = cb.from_user
    summary = f"{data.get('brand')} {data.get('model')} от {data.get('min_year')} г."
    payload = {
        "brand": data.get("brand"),
        "model": data.get("model"),
        "min_year": data.get("min_year"),
        "drive_type": data.get("drive_type"),
        "gearbox": data.get("gearbox"),
        "max_mileage": data.get("max_mileage"),
        "condition": data.get("condition"),
        "auction_damage": data.get("auction_damage"),
        "auction_max_bid_usd": data.get("auction_max_bid_usd"),
        "summary": summary,
    }
    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg.id, tg.username)
        req = Request(
            user_id=user.id,
            kind="car",
            payload_json=json.dumps(payload, ensure_ascii=False),
            payment_method=data.get("payment_method"),
            status="new",
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
        if cb.bot is not None:
            await notify_admins_new_request(cb.bot, req, user)

    await state.clear()
    pay = "СБП" if data.get("payment_method") == "sbp" else "Счёт (PDF)"
    text = (
        f"✅ <b>Заявка #{req.id} принята.</b>\n\n"
        f"Тип: 🚗 авто ({'дилер' if data.get('condition') == 'dealer' else 'аукцион'})\n"
        f"{summary}\n"
        f"Привод: {data.get('drive_type')}, КПП: {data.get('gearbox')}, "
        f"пробег ≤ {data.get('max_mileage'):,} км\n".replace(",", " ")
        + (
            f"Повреждения: {data.get('auction_damage')}\n"
            f"Макс. ставка: {data.get('auction_max_bid_usd'):,} $\n".replace(",", " ")
            if data.get("condition") == "auction"
            else ""
        )
        + f"Оплата: <b>{pay}</b>\n\n"
        "Менеджер свяжется с вами в ближайшее время."
    )
    if cb.message:
        await cb.message.edit_text(text, reply_markup=main_menu())
    await cb.answer("Заявка отправлена")
