"""Админские команды + создание оферов + обработка выбора пользователем."""

from __future__ import annotations

import asyncio
import json
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)
from sqlalchemy import func, select

from ..config import get_settings
from ..db import Offer, Request, SessionLocal, User
from ..keyboards import (
    admin_confirm_paid_kb,
    client_paid_kb,
    main_menu,
    offer_choice_kb,
    payment_method_kb,
    reply_cancel,
    welcome_reply_kb,
)
from ..notify import format_request, request_action_kb
from ..states import AdminFlow
from ..utils.payments import (
    prepay_line,
    compute_prepayment,
    make_invoice_pdf,
    make_sbp_qr,
    payment_caption,
)
from ..utils.text import h
from ..utils.validators import parse_int

router = Router(name="admin")
log = logging.getLogger(__name__)


def _is_admin(tg_id: int) -> bool:
    return tg_id in get_settings().admin_ids


# --------------------------------------------------------------------------- #
#  /inbox, /inbox_new, /request, /stats
# --------------------------------------------------------------------------- #
@router.message(Command("inbox"))
async def cmd_inbox(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        res = await session.execute(
            select(Request).order_by(Request.created_at.desc()).limit(50)
        )
        rows = res.scalars().all()
    await _send_request_list(message, rows, "📥 Входящие (последние 50):")


@router.message(Command("inbox_new"))
async def cmd_inbox_new(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        res = await session.execute(
            select(Request).where(Request.status == "new").order_by(Request.created_at.desc())
        )
        rows = res.scalars().all()
    await _send_request_list(message, rows, "📥 Необработанные заявки:")


async def _send_request_list(message: Message, rows: list[Request], header: str) -> None:
    if not rows:
        await message.answer(f"{header}\n\nпусто.")
        return
    lines = [header, ""]
    async with SessionLocal() as session:
        for r in rows[:30]:
            user = await session.get(User, r.user_id)
            payload = json.loads(r.payload_json)
            summary = payload.get("summary", "")
            kind_ru = {"car": "🚗", "parts": "🔧", "shop": "🛒"}.get(r.kind, r.kind)
            uname = f"@{user.username}" if user and user.username else (user.name if user else "?")
            lines.append(
                f"#{r.id} {kind_ru} {summary[:50]} — {uname} — {r.status}"
                f"  /request_{r.id}"
            )
    await message.answer("\n".join(lines))


@router.message(Command("request"))
@router.message(F.text.regexp(r"^/request_(\d+)$"))
async def cmd_request(message: Message, command: CommandObject | None = None) -> None:
    if not _is_admin(message.from_user.id):
        return
    text = message.text or ""
    # поддерживаем и "/request 10", и "/request_10"
    req_id: int | None = None
    if command and command.args:
        req_id = parse_int(command.args)
    else:
        import re

        m = re.match(r"^/request_(\d+)$", text)
        if m:
            req_id = int(m.group(1))
    if req_id is None:
        await message.answer("Использование: <code>/request ID</code> или <code>/request_ID</code>")
        return
    async with SessionLocal() as session:
        req = await session.get(Request, req_id)
        if req is None:
            await message.answer(f"Заявка #{req_id} не найдена.")
            return
        user = await session.get(User, req.user_id)
    await message.answer(
        format_request(req, user),
        reply_markup=request_action_kb(req.id, user.tg_id),
    )
    payload = json.loads(req.payload_json)
    if payload.get("photo_file_id"):
        await message.answer_photo(payload["photo_file_id"], caption=f"Фото к заявке #{req.id}")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        by_kind = (
            await session.execute(
                select(Request.kind, func.count()).group_by(Request.kind)
            )
        ).all()
        offers_total = (await session.execute(select(func.count()).select_from(Offer))).scalar_one()
        offers_by_status = (
            await session.execute(
                select(Offer.status, func.count()).group_by(Offer.status)
            )
        ).all()
    kind_ru = {"car": "🚗", "parts": "🔧", "shop": "🛒"}
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"Пользователей: <b>{total_users}</b>\n"
        f"Заявок по типам:\n"
        + "\n".join(f"  {kind_ru.get(k, k)} {k}: {n}" for k, n in by_kind)
        + "\n\n"
        f"Оферов всего: <b>{offers_total}</b>\n"
        + "\n".join(f"  {s}: {n}" for s, n in offers_by_status)
    )
    await message.answer(text)


# --------------------------------------------------------------------------- #
#  /offer <user_id> <sum> — быстрый офер; либо кнопка «Создать оффер»
# --------------------------------------------------------------------------- #
@router.message(Command("offer"))
async def cmd_offer(message: Message, state: FSMContext, command: CommandObject) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (command.args or "").split()
    if len(parts) >= 1:
        target = parse_int(parts[0])
        if target is None:
            await message.answer("Использование: <code>/offer &lt;user_tg_id&gt; [сумма_руб]</code>")
            return
        await state.update_data(target_user_id=target)
    if len(parts) >= 2:
        amount = parse_int(parts[1])
        if amount:
            await state.update_data(offer_price_rub=amount)
    await _start_offer_flow(message, state)


@router.callback_query(F.data.startswith("adm:make_offer:"))
async def cb_make_offer(cb: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Только админ", show_alert=True)
        return
    _, _, user_tg_id, req_id = (cb.data or "").split(":")
    await state.update_data(target_user_id=int(user_tg_id), source_request_id=int(req_id))
    await _start_offer_flow(cb.message, state)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:req_done:"))
async def cb_req_done(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id):
        await cb.answer("Только админ", show_alert=True)
        return
    _, _, req_id = (cb.data or "").split(":")
    async with SessionLocal() as session:
        req = await session.get(Request, int(req_id))
        if req is None:
            await cb.answer("Заявка не найдена", show_alert=True)
            return
        req.status = "done"
        await session.commit()
    await cb.answer("Заявка помечена обработанной")
    if cb.message:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


async def _start_offer_flow(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if "offer_title" not in data:
        await state.set_state(AdminFlow.offer_title)
        await message.answer(
            "📨 <b>Создание оффера</b>\n\nНазвание (1-256 символов):",
            reply_markup=reply_cancel(),
        )
        return


@router.message(AdminFlow.offer_title, F.text)
async def offer_title(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if not (1 <= len(title) <= 256):
        await message.answer("Название 1-256 символов.")
        return
    await state.update_data(offer_title=title)
    await state.set_state(AdminFlow.offer_description)
    await message.answer("Описание (до 2000 символов):")


@router.message(AdminFlow.offer_description, F.text)
async def offer_desc(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    desc = (message.text or "").strip()
    if not (1 <= len(desc) <= 2000):
        await message.answer("Описание 1-2000 символов.")
        return
    await state.update_data(offer_description=desc)
    data = await state.get_data()
    if "offer_price_rub" in data:
        await _commit_offer(message, state)
    else:
        await state.set_state(AdminFlow.offer_price_rub)
        await message.answer("Сумма, ₽ (целое число):")


@router.message(AdminFlow.offer_price_rub, F.text)
async def offer_price(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    amount = parse_int(message.text or "")
    if amount is None or amount <= 0:
        await message.answer("Сумму не понял. Введите целое число рублей, например 1500000")
        return
    await state.update_data(offer_price_rub=amount)
    await _commit_offer(message, state)


async def _commit_offer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    target_tg = int(data["target_user_id"])
    title = data["offer_title"]
    desc = data["offer_description"]
    price = int(data["offer_price_rub"])
    admin_tg_id = message.from_user.id
    source_request_id = data.get("source_request_id")

    async with SessionLocal() as session:
        res = await session.execute(select(User).where(User.tg_id == target_tg))
        user = res.scalar_one_or_none()
        if user is None:
            await message.answer(
                f"Пользователь tg_id=<code>{target_tg}</code> не найден в БД. "
                "Он должен сначала написать /start боту."
            )
            await state.clear()
            return
        # если оффер создаётся из кнопки «Создать оффер» под конкретной
        # заявкой — берём её kind; иначе kind None (предоплата без минимума)
        kind: str | None = None
        if source_request_id is not None:
            src = await session.get(Request, int(source_request_id))
            if src is not None:
                kind = src.kind
        offer = Offer(
            user_id=user.id,
            admin_tg_id=admin_tg_id,
            title=title,
            description=desc,
            price_rub=price,
            kind=kind,
            status="sent",
        )
        session.add(offer)
        await session.commit()
        await session.refresh(offer)

    await state.clear()

    prepay = compute_prepayment(price, kind=kind)
    prepay_str = prepay_line(prepay, kind=kind)
    text_to_user = (
        f"📨 <b>Новое предложение #{offer.id}</b>\n\n"
        f"<b>{h(title)}</b>\n\n"
        f"{h(desc)}\n\n"
        f"Сумма: <b>{price:,} ₽</b>\n".replace(",", " ")
        + f"{prepay_str}\n\n"
        + "Нажмите «Сделать выбор», чтобы принять предложение и выбрать способ оплаты."
    )
    try:
        await message.bot.send_message(
            chat_id=target_tg,
            text=text_to_user,
            reply_markup=offer_choice_kb(offer.id),
        )
    except Exception as e:
        await message.answer(f"⚠️ Не удалось отправить оффер пользователю: {e}")
        return

    await message.answer(
        f"✅ Оффер #{offer.id} отправлен пользователю tg_id=<code>{target_tg}</code>.",
        reply_markup=main_menu(),
    )


# --------------------------------------------------------------------------- #
#  Пользователь нажал «Сделать выбор» / «Отклонить» / выбрал оплату
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.regexp(r"^offer:(\d+):(accept|decline)$"))
async def offer_user_choice(cb: CallbackQuery) -> None:
    _, offer_id_s, action = (cb.data or "").split(":")
    offer_id = int(offer_id_s)
    async with SessionLocal() as session:
        offer = await session.get(Offer, offer_id)
        if offer is None:
            await cb.answer("Оффер не найден", show_alert=True)
            return
        user = await session.get(User, offer.user_id)
        if user is None or user.tg_id != cb.from_user.id:
            await cb.answer("Этот оффер — не ваш", show_alert=True)
            return
        if action == "decline":
            offer.status = "declined"
            await session.commit()
            if cb.message:
                await cb.message.edit_text(
                    f"❌ Оффер #{offer.id} отклонён.", reply_markup=main_menu()
                )
            await cb.answer()
            await _notify_admins(cb.bot, f"❌ Пользователь tg_id={user.tg_id} отклонил оффер #{offer.id}")
            return
        # accept
        offer.status = "accepted"
        await session.commit()
    if cb.message:
        await cb.message.edit_text(
            f"✅ Оффер #{offer.id} принят. Выберите способ оплаты:",
            reply_markup=payment_method_kb(f"offer:{offer.id}"),
        )
    await cb.answer()


@router.callback_query(F.data.regexp(r"^offer:(\d+):pay:(sbp|invoice)$"))
async def offer_pay(cb: CallbackQuery, bot: Bot) -> None:
    """Клиент выбрал способ оплаты.

    Бот отправляет инструкцию + QR/PDF + кнопку «Я оплатил» клиенту, а админу —
    уведомление с кнопкой «✅ Оплата получена». Деньги поступают на счёт
    самозанятого вне Telegram (СБП C2C по номеру или по реквизитам), бот лишь
    выступает курьером инструкций и трекером статуса.
    """
    _, offer_id_s, _, method = (cb.data or "").split(":")
    offer_id = int(offer_id_s)
    async with SessionLocal() as session:
        offer = await session.get(Offer, offer_id)
        if offer is None:
            await cb.answer("Оффер не найден", show_alert=True)
            return
        user = await session.get(User, offer.user_id)
        if user is None or user.tg_id != cb.from_user.id:
            await cb.answer("Этот оффер — не ваш", show_alert=True)
            return
        offer.status = "paid_sbp" if method == "sbp" else "paid_invoice"
        await session.commit()
    prepay = compute_prepayment(offer.price_rub, kind=offer.kind)
    caption = payment_caption(offer.id, prepay)
    paid_kb = client_paid_kb(
        offer.id,
        pay_url=get_settings().payee_payment_url,
        amount_rub=prepay,
    )

    if method == "sbp":
        png, _payload = make_sbp_qr(offer.id, user.tg_id, prepay)
        await cb.message.answer_photo(
            BufferedInputFile(png, filename=f"sbp_{offer.id}.png"),
            caption=caption,
            reply_markup=paid_kb,
        )
    else:
        pdf = make_invoice_pdf(
            offer.id,
            user.tg_id,
            user.name,
            offer.title,
            offer.description,
            offer.price_rub,
            prepay,
            kind=offer.kind,
        )
        await cb.message.answer_document(
            BufferedInputFile(pdf, filename=f"invoice_{offer.id}.pdf"),
            caption=caption,
            reply_markup=paid_kb,
        )

    if cb.message:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await cb.answer("Документы отправлены")

    # Админу — уведомление с inline-кнопкой «✅ Оплата получена».
    uname = f"@{h(user.username)}" if user.username else "—"
    admin_text = (
        f"💰 <b>Ожидание оплаты — оффер #{offer.id}</b>\n\n"
        f"Клиент: {h(user.name) or '—'} ({uname}, tg_id=<code>{user.tg_id}</code>)\n"
        f"Способ: <b>{method.upper()}</b>\n"
        f"Полная сумма: <b>{offer.price_rub:,} ₽</b>\n".replace(",", " ")
        + f"<b>Предоплата к получению: {prepay:,} ₽</b>\n".replace(",", " ")
        + "\nКогда увидишь поступление в банке — нажми "
        "«✅ Оплата получена»."
    )
    await _notify_admins(bot, admin_text, kb=admin_confirm_paid_kb(offer.id))


@router.callback_query(F.data.regexp(r"^offer:(\d+):claim_paid$"))
async def offer_claim_paid(cb: CallbackQuery, bot: Bot) -> None:
    """Клиент жмёт «✅ Я оплатил». Бот меняет статус и пушит админам напоминание."""
    _, offer_id_s, _ = (cb.data or "").split(":")
    offer_id = int(offer_id_s)
    async with SessionLocal() as session:
        offer = await session.get(Offer, offer_id)
        if offer is None:
            await cb.answer("Оффер не найден", show_alert=True)
            return
        user = await session.get(User, offer.user_id)
        if user is None or user.tg_id != cb.from_user.id:
            await cb.answer("Этот оффер — не ваш", show_alert=True)
            return
        if offer.status == "confirmed_paid":
            await cb.answer("Оплата уже подтверждена админом ✅", show_alert=True)
            return
        offer.status = "claimed_paid"
        await session.commit()
    if cb.message:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        # Спасибо клиенту — без inline-кнопок, чтобы дать «выдохнуть».
        await cb.message.answer(
            f"🙏 <b>Спасибо!</b>\n\n"
            f"Сообщили продавцу о вашей оплате по офферу #{offer.id}. "
            "Как только увидим поступление, подтвердим и пришлём чек "
            "самозанятого (НПД) от ФНС.\n\n"
            "Через пару секунд вернёмся к главному меню — можно оформить "
            "ещё одну заявку.",
        )
    await cb.answer()

    uname = f"@{h(user.username)}" if user.username else "—"
    prepay = compute_prepayment(offer.price_rub, kind=offer.kind)
    await _notify_admins(
        bot,
        f"📨 <b>Клиент сообщил об оплате</b> — оффер #{offer.id}\n"
        f"Клиент: {h(user.name) or '—'} ({uname}, tg_id=<code>{user.tg_id}</code>)\n"
        f"Ожидаем: <b>{prepay:,} ₽</b>\n".replace(",", " ")
        + "Проверь приход в Тинькофф и нажми «✅ Оплата получена».",
        kb=admin_confirm_paid_kb(offer.id),
    )

    # Пауза 3 секунды — чтобы клиент успел прочитать «Спасибо» — и затем
    # пере-показываем главное меню, чтобы можно было сразу оформить
    # следующую заявку без ручного /menu.
    if cb.message:
        await asyncio.sleep(3)
        try:
            await cb.message.answer(
                "👋",
                reply_markup=welcome_reply_kb(),
            )
            await cb.message.answer(
                "📍 Главное меню — выбери, что сделать дальше:",
                reply_markup=main_menu(),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось показать главное меню после claim_paid: %s", e)


@router.callback_query(F.data.regexp(r"^offer:(\d+):confirm_paid$"))
async def offer_confirm_paid(cb: CallbackQuery, bot: Bot) -> None:
    """Админ подтверждает приход денег. Бот:

    1. Меняет статус оффера на ``confirmed_paid``.
    2. Шлёт клиенту радостное сообщение про чек.
    3. Шлёт админу напоминалку «пробей чек в Мой налог» с готовыми полями.
    """
    if not _is_admin(cb.from_user.id):
        await cb.answer("Только для админов", show_alert=True)
        return
    _, offer_id_s, _ = (cb.data or "").split(":")
    offer_id = int(offer_id_s)
    async with SessionLocal() as session:
        offer = await session.get(Offer, offer_id)
        if offer is None:
            await cb.answer("Оффер не найден", show_alert=True)
            return
        user = await session.get(User, offer.user_id)
        if user is None:
            await cb.answer("Пользователь не найден", show_alert=True)
            return
        if offer.status == "confirmed_paid":
            await cb.answer("Уже подтверждено ранее", show_alert=True)
            return
        offer.status = "confirmed_paid"
        await session.commit()
    prepay = compute_prepayment(offer.price_rub, kind=offer.kind)
    purpose = f"Предоплата по офферу ETP-{offer.id:06d}"

    # Клиенту — подтверждение.
    try:
        await bot.send_message(
            user.tg_id,
            f"✅ <b>Оплата по офферу #{offer.id} подтверждена</b>\n\n"
            f"Сумма: <b>{prepay:,} ₽</b>\n".replace(",", " ")
            + f"Назначение: {purpose}\n\n"
            "Чек самозанятого (НПД) придёт от ФНС в течение 24 часов "
            "от продавца через приложение «Мой налог».",
            reply_markup=main_menu(),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось уведомить клиента %s: %s", user.tg_id, e)

    # Обновим админу его сообщение, чтобы кнопка не висела.
    if cb.message:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    # Админам — напоминалка пробить чек самозанятого через «Мой налог».
    uname = f"@{h(user.username)}" if user.username else "—"
    reminder = (
        f"🧾 <b>Не забудь пробить чек самозанятого</b> — оффер #{offer.id}\n\n"
        "После фактического поступления оплаты на расчётный счёт пробей чек "
        "через приложение «Мой налог» (lknpd.nalog.ru) и перешли его клиенту "
        "в этот же чат.\n\n"
        f"• Сумма: <b>{prepay:,} ₽</b>\n".replace(",", " ")
        + f"• Назначение: <i>{h(purpose)}</i>\n"
        f"• Покупатель: {h(user.name) or 'клиент'} (tg {uname}, "
        f"tg_id=<code>{user.tg_id}</code>)"
    )
    await _notify_admins(bot, reminder)
    await cb.answer("Подтверждено ✅")


async def _notify_admins(bot: Bot, text: str, kb=None) -> None:
    for admin_id in get_settings().admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except Exception as e:
            log.warning("Не удалось отправить админу %s: %s", admin_id, e)
