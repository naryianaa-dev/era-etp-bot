"""Ветка «Покупки» — товар + URL + комментарии."""

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import Request, SessionLocal, get_or_create_user
from ..keyboards import reply_cancel
from ..notify import notify_admins_new_request
from ..states import ShopFlow
from ..utils.text import h
from ..utils.validators import is_valid_url
from ._post_request import finish_request_accepted_for_message

router = Router(name="shop")


@router.callback_query(F.data == "menu:shop")
async def cb_enter_shop(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ShopFlow.product_name)
    if cb.message:
        await cb.message.edit_text(
            "🛒 <b>Покупки</b>\n\nНазвание товара:"
        )
        await cb.message.answer("Для отмены нажмите «Отмена».", reply_markup=reply_cancel())
    await cb.answer()


@router.message(ShopFlow.product_name, F.text)
async def on_name(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if not (1 <= len(val) <= 256):
        await message.answer("Название 1-256 символов.")
        return
    await state.update_data(product_name=val)
    await state.set_state(ShopFlow.url)
    await message.answer("Ссылка на товар (URL). Начинается с http:// или https://")


@router.message(ShopFlow.url, F.text)
async def on_url(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not is_valid_url(url):
        await message.answer(
            "Это не похоже на URL. Пример: <code>https://www.amazon.com/dp/B08N5WRWNW</code>"
        )
        return
    await state.update_data(url=url)
    await state.set_state(ShopFlow.comments)
    await message.answer(
        "Комментарии / пожелания (размер, цвет, кол-во и т.п.). "
        "Если нет — напишите «-»:"
    )


@router.message(ShopFlow.comments, F.text)
async def on_comments(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if val in ("-", "—", "нет"):
        val = ""
    if len(val) > 1000:
        await message.answer("Слишком длинный комментарий (>1000 символов).")
        return
    data = await state.get_data()
    tg = message.from_user
    summary = f"{data.get('product_name')}"
    payload = {
        "product_name": data.get("product_name"),
        "url": data.get("url"),
        "comments": val,
        "summary": summary,
    }
    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg.id, tg.username)
        req = Request(
            user_id=user.id, kind="shop",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        session.add(req)
        await session.commit()
        await session.refresh(req)
        if message.bot is not None:
            await notify_admins_new_request(message.bot, req, user)
    await state.clear()
    summary_html = (
        f"🛒 <b>Покупка</b>\n"
        f"Товар: {h(data.get('product_name'))}\n"
        f"Ссылка: {h(data.get('url'))}\n"
        + (f"Комментарии: {h(val)}\n" if val else "")
    )
    await finish_request_accepted_for_message(
        message, request_id=req.id, summary_html=summary_html
    )
