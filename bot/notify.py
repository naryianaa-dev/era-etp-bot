"""Хелперы: форматирование и отправка уведомлений админам."""

from __future__ import annotations

import json
import logging
from typing import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import get_settings
from .db import Request, User

log = logging.getLogger(__name__)


def _kind_ru(kind: str) -> str:
    return {"car": "🚗 Авто", "parts": "🔧 Запчасти", "shop": "🛒 Покупка"}.get(kind, kind)


def format_request(req: Request, user: User) -> str:
    """Красивое представление заявки для админа."""
    payload = json.loads(req.payload_json)
    uname = f"@{user.username}" if user.username else "—"
    header = (
        f"<b>Новая заявка #{req.id}</b> — {_kind_ru(req.kind)}\n"
        f"Пользователь: {user.name or '—'} ({uname}, tg_id=<code>{user.tg_id}</code>)\n"
        f"Дата: {req.created_at.strftime('%d.%m.%Y %H:%M')}\n"
    )
    body_lines: list[str] = []
    if req.kind == "car":
        body_lines.append(
            f"{payload.get('brand')} {payload.get('model')} от {payload.get('min_year')} г."
        )
        body_lines.append(
            f"Привод: {payload.get('drive_type')}, КПП: {payload.get('gearbox')}, "
            f"пробег ≤ {payload.get('max_mileage')}"
        )
        cond = payload.get("condition")
        if cond == "dealer":
            body_lines.append("Источник: <b>Дилер</b>")
        else:
            body_lines.append("Источник: <b>Аукцион</b>")
            body_lines.append(f"Повреждения: {payload.get('auction_damage')}")
            body_lines.append(f"Макс. ставка: {payload.get('auction_max_bid_usd')} $")
        body_lines.append(f"Оплата: {req.payment_method or '—'}")
    elif req.kind == "parts":
        body_lines.append(
            f"{payload.get('brand')} {payload.get('model')} {payload.get('year')}"
        )
        if payload.get("vin"):
            body_lines.append(f"VIN: <code>{payload['vin']}</code>")
        body_lines.append(f"Деталь: {payload.get('part_name')}")
        if payload.get("part_number"):
            body_lines.append(f"Артикул: <code>{payload['part_number']}</code>")
        if payload.get("photo_file_id"):
            body_lines.append("Фото: ✅ (отправится отдельным сообщением)")
    elif req.kind == "shop":
        body_lines.append(f"Товар: {payload.get('product_name')}")
        body_lines.append(f"Ссылка: {payload.get('url')}")
        if payload.get("comments"):
            body_lines.append(f"Комментарии: {payload['comments']}")
    return header + "\n" + "\n".join(body_lines)


def request_action_kb(request_id: int, user_tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📨 Создать оффер",
                    callback_data=f"adm:make_offer:{user_tg_id}:{request_id}",
                ),
                InlineKeyboardButton(
                    text="✅ Пометить обработанной",
                    callback_data=f"adm:req_done:{request_id}",
                ),
            ],
        ]
    )


async def notify_admins_new_request(bot: Bot, req: Request, user: User) -> None:
    st = get_settings()
    admins: Iterable[int] = st.admin_ids
    if not admins:
        log.info("ADMIN_IDS пусто — уведомлений никому не шлём")
        return
    text = format_request(req, user)
    kb = request_action_kb(req.id, user.tg_id)
    payload = json.loads(req.payload_json)
    photo_id = payload.get("photo_file_id")
    for admin_id in admins:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
            if photo_id:
                await bot.send_photo(admin_id, photo_id, caption=f"Фото к заявке #{req.id}")
        except TelegramAPIError as e:
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)
