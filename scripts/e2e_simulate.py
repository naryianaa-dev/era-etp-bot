"""End-to-end симуляция бота без реальных вызовов Telegram API.

Работает так:
  1. Создаётся Bot с настоящим токеном (для корректного парсинга ID),
     но session подменяется на MockSession.
  2. MockSession перехватывает ВСЕ исходящие запросы (sendMessage,
     sendPhoto, sendDocument, editMessageReplyMarkup, ...), возвращает
     правдоподобные заглушки и складывает пары «запрос — ответ» в журнал.
  3. Генерируются Update-события (сообщения пользователя, нажатия
     inline-кнопок) и передаются в dp.feed_update(bot, update) — так
     же, как это делает long-polling в проде.
  4. По завершению каждого сценария печатается транскрипт диалога.

Запуск:   python scripts/e2e_simulate.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap
import typing as t
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------- env ----------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", os.environ.get("BOT_TOKEN", "0:test"))
os.environ["ADMIN_IDS"] = os.environ.get("ADMIN_IDS", "11111111")
os.environ["DB_PATH"]   = os.environ.get("DB_PATH",
                           str(Path(tempfile.gettempdir()) / "era_e2e.sqlite3"))

# Wipe existing test DB so each run starts clean
db_path = Path(os.environ["DB_PATH"])
if db_path.exists():
    db_path.unlink()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------- imports from the bot package --------------------------------
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery, Chat, InlineKeyboardButton, InlineKeyboardMarkup,
    Message, PhotoSize, ReplyKeyboardMarkup, Update, User,
)

from bot.db import init_db
from bot.handlers import admin as h_admin
from bot.handlers import car as h_car
from bot.handlers import common as h_common
from bot.handlers import parts as h_parts
from bot.handlers import shop as h_shop
from bot.handlers import start as h_start


# ======================================================================
#  MockSession
# ======================================================================

@dataclass
class RecordedCall:
    method: str
    args:   dict
    ts:     datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MockSession(BaseSession):
    """Ничего не шлёт в Telegram, возвращает правдоподобные заглушки."""

    _fake_msg_id = 100

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[RecordedCall] = []

    async def close(self) -> None:  # noqa: D401 – match signature
        pass

    async def make_request(
        self,
        bot: Bot,
        call: TelegramMethod,
        timeout: int | None = None,
    ) -> t.Any:
        args = call.model_dump(exclude_none=True)
        self.calls.append(RecordedCall(method=call.__api_method__, args=args))
        return self._fake_response(call, args)

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError

    def _fake_response(self, call: TelegramMethod, args: dict) -> t.Any:
        MockSession._fake_msg_id += 1
        msg_id = MockSession._fake_msg_id
        method = call.__api_method__
        chat_id = args.get("chat_id") or args.get("user_id") or 0

        # Minimal Message stub acceptable to pydantic Message(...)
        if method in {
            "sendMessage", "sendPhoto", "sendDocument", "sendMediaGroup",
            "editMessageText", "forwardMessage", "copyMessage",
        }:
            return Message.model_validate({
                "message_id": msg_id,
                "date":       int(datetime.now(timezone.utc).timestamp()),
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": 8229318891, "is_bot": True,
                         "first_name": "era_etp_bot", "username": "era_etp_bot"},
                "text": args.get("text") or args.get("caption") or "",
            })
        if method == "getMe":
            return User.model_validate({
                "id": 8229318891, "is_bot": True, "first_name": "era_etp_bot",
                "username": "era_etp_bot",
            })
        if method in {"answerCallbackQuery", "setMyCommands",
                      "deleteMyCommands"}:
            return True
        return True


# ======================================================================
#  helpers to build Update objects
# ======================================================================

USER = User(id=12345, is_bot=False, first_name="Нарияна",
            username="naryiana_test", language_code="ru")
ADMIN = User(id=11111111, is_bot=False, first_name="Админ",
             username="admin_test", language_code="ru")

CHAT_USER  = Chat(id=USER.id,  type="private")
CHAT_ADMIN = Chat(id=ADMIN.id, type="private")


_update_id = 1
_message_id = 1


def _next_ids() -> tuple[int, int]:
    global _update_id, _message_id
    _update_id  += 1
    _message_id += 1
    return _update_id, _message_id


def msg_update(text: str, *, as_admin: bool = False) -> Update:
    uid, mid = _next_ids()
    from_user = ADMIN if as_admin else USER
    chat      = CHAT_ADMIN if as_admin else CHAT_USER
    m = Message.model_validate({
        "message_id": mid,
        "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": chat.model_dump(),
        "from": from_user.model_dump(),
        "text": text,
    })
    return Update.model_validate({"update_id": uid, "message": m.model_dump()})


def cb_update(data: str, *, as_admin: bool = False,
              inline_msg_id: int = 1) -> Update:
    uid, _ = _next_ids()
    from_user = ADMIN if as_admin else USER
    chat      = CHAT_ADMIN if as_admin else CHAT_USER
    m = {
        "message_id": inline_msg_id,
        "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": chat.model_dump(),
        "from": {"id": 8229318891, "is_bot": True,
                 "first_name": "era_etp_bot", "username": "era_etp_bot"},
        "text": "[bot msg with buttons]",
    }
    cb = {
        "id": f"cb{uid}",
        "from": from_user.model_dump(),
        "chat_instance": "x",
        "data": data,
        "message": m,
    }
    return Update.model_validate({"update_id": uid, "callback_query": cb})


# ======================================================================
#  Transcript printing
# ======================================================================

def trim(text: str, width: int = 120) -> str:
    text = text or ""
    lines = text.splitlines() or [text]
    out: list[str] = []
    for ln in lines:
        if len(ln) <= width:
            out.append(ln)
        else:
            out.append(ln[: width - 1] + "…")
    return "\n".join(out)


def drain_calls(session: MockSession, as_admin: bool = False) -> None:
    audience = "АДМИН" if as_admin else "ЮЗЕР"
    for c in session.calls:
        method = c.method
        args   = c.args
        chat   = args.get("chat_id")
        if method == "sendMessage":
            prefix = "BOT→ADMIN" if chat == ADMIN.id else "BOT→USER"
            print(f"  {prefix} [sendMessage]")
            txt = trim(args.get("text", ""))
            for line in txt.splitlines():
                print(f"    {line}")
            kb = args.get("reply_markup") or {}
            if isinstance(kb, dict) and kb.get("inline_keyboard"):
                for row in kb["inline_keyboard"]:
                    btns = " | ".join(
                        f"[{b.get('text','?')} → {b.get('callback_data','')}]"
                        for b in row
                    )
                    print(f"    ⏺ {btns}")
        elif method == "sendPhoto":
            prefix = "BOT→ADMIN" if chat == ADMIN.id else "BOT→USER"
            caption = trim(args.get("caption") or "[photo]")
            print(f"  {prefix} [sendPhoto] {caption}")
        elif method == "sendDocument":
            prefix = "BOT→ADMIN" if chat == ADMIN.id else "BOT→USER"
            fname = args.get("document")
            caption = trim(args.get("caption") or "[document]")
            print(f"  {prefix} [sendDocument] {caption}")
        elif method == "answerCallbackQuery":
            txt = args.get("text") or ""
            if txt:
                print(f"  BOT→UI [callback-ack] {trim(txt)}")
        elif method in {"editMessageText", "editMessageReplyMarkup"}:
            print(f"  BOT→UI [{method}]")
            if args.get("text"):
                print(f"    {trim(args['text'])}")
        else:
            print(f"  BOT→API [{method}] {list(args.keys())}")
    session.calls.clear()


# ======================================================================
#  main orchestration
# ======================================================================

async def run_scenario(
    name: str,
    dp: Dispatcher,
    bot: Bot,
    steps: list[tuple[str, Update]],
) -> None:
    sep = "━" * 100
    print(f"\n{sep}\nСЦЕНАРИЙ: {name}\n{sep}")
    session = t.cast(MockSession, bot.session)
    for label, upd in steps:
        who = "ЮЗЕР" if upd.message and upd.message.from_user.id == USER.id \
              else "АДМИН" if upd.message and upd.message.from_user.id == ADMIN.id \
              else "ЮЗЕР(cb)" if upd.callback_query and upd.callback_query.from_user.id == USER.id \
              else "АДМИН(cb)"
        text = (upd.message.text if upd.message
                else f"callback:{upd.callback_query.data}")
        print(f"\n{who}: {text}    ← {label}")
        session.calls.clear()
        try:
            await dp.feed_update(bot, upd)
        except Exception as e:
            print(f"  !!! ИСКЛЮЧЕНИЕ: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return
        drain_calls(session)


async def main() -> None:
    await init_db()

    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=MockSession(),
    )

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(h_common.router)
    dp.include_router(h_admin.router)
    dp.include_router(h_start.router)
    dp.include_router(h_car.router)
    dp.include_router(h_parts.router)
    dp.include_router(h_shop.router)

    print("═" * 100)
    print("E2E СИМУЛЯЦИЯ era_etp_bot  (все запросы к Telegram API подменяются)")
    print(f"USER id={USER.id} ({USER.first_name})")
    print(f"ADMIN id={ADMIN.id} ({ADMIN.first_name})")
    print("═" * 100)

    # -------- сценарий 1: /start + регистрация имени -----------------
    await run_scenario("Регистрация нового юзера + главное меню", dp, bot, [
        ("первый /start", msg_update("/start")),
        ("ввод имени",    msg_update("Нарияна")),
    ])

    # -------- сценарий 2: ветка АВТО / Дилер / СБП -------------------
    await run_scenario("Авто → Дилер → СБП", dp, bot, [
        ("клик 'Авто'",          cb_update("menu:car")),
        ("марка",                msg_update("BMW")),
        ("модель",               msg_update("X5")),
        ("мин. год",             msg_update("2018")),
        ("привод AWD",           cb_update("car_drive:AWD")),
        ("коробка AT",           cb_update("car_gb:AT")),
        ("макс. пробег",         msg_update("100000")),
        ("состояние: Дилер",     cb_update("car_cond:dealer")),
        ("оплата СБП",           cb_update("car_dealer:pay:sbp")),
    ])

    # -------- сценарий 3: ветка АВТО / Аукцион / Счёт ----------------
    await run_scenario("Авто → Аукцион → Счёт", dp, bot, [
        ("клик 'Авто'",          cb_update("menu:car")),
        ("марка",                msg_update("Toyota")),
        ("модель",               msg_update("Camry")),
        ("мин. год",             msg_update("2020")),
        ("привод FWD",           cb_update("car_drive:FWD")),
        ("коробка CVT",          cb_update("car_gb:CVT")),
        ("макс. пробег",         msg_update("50 000 км")),
        ("состояние: Аукцион",   cb_update("car_cond:auction")),
        ("описание повреждений", msg_update("Небольшой фронт, airbag не сработал")),
        ("макс. ставка USD",     msg_update("15000$")),
        ("оплата Счёт",          cb_update("car_auction:pay:invoice")),
    ])

    # -------- сценарий 4: ветка ЗАПЧАСТИ (с артикулом) ---------------
    await run_scenario("Запчасти → с артикулом", dp, bot, [
        ("клик 'Запчасти'",      cb_update("menu:parts")),
        ("марка",                msg_update("Mercedes")),
        ("модель",               msg_update("E-Class W213")),
        ("год",                  msg_update("2019")),
        ("VIN",                  msg_update("WDDZF8DB5KA564512")),
        ("название детали",      msg_update("Передний бампер")),
        ("есть артикул — Да",    cb_update("parts_art:yes")),
        ("артикул",              msg_update("A2138850038")),
    ])

    # -------- сценарий 5: ветка ЗАПЧАСТИ (без артикула, без фото) ---
    await run_scenario("Запчасти → без артикула, без фото", dp, bot, [
        ("клик 'Запчасти'",      cb_update("menu:parts")),
        ("марка",                msg_update("LADA")),
        ("модель",               msg_update("Vesta")),
        ("год",                  msg_update("2021")),
        ("VIN",                  msg_update("нет")),
        ("название детали",      msg_update("Задний фонарь правый")),
        ("есть артикул — Нет",   cb_update("parts_art:no")),
        ("есть фото — Нет",      cb_update("parts_photo:no")),
    ])

    # -------- сценарий 6: ветка ПОКУПКИ --------------------------------
    await run_scenario("Покупки", dp, bot, [
        ("клик 'Покупки'",       cb_update("menu:shop")),
        ("товар",                msg_update("Apple MacBook Pro 16 M3 Max")),
        ("URL",                  msg_update("https://apple.com/shop/macbook-pro-16-m3-max")),
        ("комментарий",          msg_update("нужно с доставкой в Москву")),
    ])

    # -------- сценарий 7: некорректный ввод (валидация) -----------
    await run_scenario("Валидация (ошибочный ввод)", dp, bot, [
        ("клик 'Авто'",          cb_update("menu:car")),
        ("марка",                msg_update("Audi")),
        ("модель",               msg_update("A4")),
        ("мин.год: текст",       msg_update("позавчера")),   # должен отругать
        ("мин.год: валидный",    msg_update("2015")),
        ("/cancel посреди FSM",  msg_update("/cancel")),
    ])

    # -------- сценарий 8: АДМИН команды /inbox, /stats --------------
    await run_scenario("Админ → /inbox, /stats", dp, bot, [
        ("/inbox",   msg_update("/inbox",  as_admin=True)),
        ("/stats",   msg_update("/stats",  as_admin=True)),
        ("/inbox_new", msg_update("/inbox_new", as_admin=True)),
    ])

    # -------- сценарий 9: АДМИН создаёт оффер + ЮЗЕР принимает + оплата СБП --
    await run_scenario(
        "Админ → /offer → юзер принимает → оплата СБП",
        dp, bot,
        [
            ("/offer <user_id>",   msg_update(f"/offer {USER.id}",   as_admin=True)),
            ("название оффера",    msg_update("BMW X5 2019 с дилерского склада", as_admin=True)),
            ("описание",           msg_update("Белый, 70 т.км., один хозяин", as_admin=True)),
            ("сумма ₽",            msg_update("2 500 000", as_admin=True)),
            ("юзер: Сделать выбор", cb_update("offer:1:accept", as_admin=False)),
            ("юзер: СБП",          cb_update("offer:1:pay:sbp", as_admin=False)),
        ],
    )

    # -------- сценарий 10: АДМИН создаёт оффер + ЮЗЕР принимает + оплата Счёт --
    await run_scenario(
        "Админ → /offer → юзер принимает → оплата Счёт",
        dp, bot,
        [
            ("/offer <user_id>",   msg_update(f"/offer {USER.id}", as_admin=True)),
            ("название",           msg_update("MacBook Pro M3 Max", as_admin=True)),
            ("описание",           msg_update("Заказ из-за рубежа с доставкой", as_admin=True)),
            ("сумма ₽",            msg_update("450000", as_admin=True)),
            ("юзер: Сделать выбор", cb_update("offer:2:accept", as_admin=False)),
            ("юзер: Счёт",         cb_update("offer:2:pay:invoice", as_admin=False)),
        ],
    )

    # -------- сценарий 11: ЮЗЕР отклоняет оффер --------------
    await run_scenario(
        "Админ → /offer → юзер отклоняет",
        dp, bot,
        [
            ("/offer <user_id>",   msg_update(f"/offer {USER.id}", as_admin=True)),
            ("название",           msg_update("Запчасть для LADA", as_admin=True)),
            ("описание",           msg_update("Фонарь 2021 года", as_admin=True)),
            ("сумма ₽",            msg_update("8500", as_admin=True)),
            ("юзер: Отклонить",    cb_update("offer:3:decline", as_admin=False)),
        ],
    )

    # -------- сценарий 12: Мои заявки ---------------
    await run_scenario("Мои заявки", dp, bot, [
        ("клик 'Мои заявки'",   cb_update("menu:my")),
    ])

    await bot.session.close()
    print("\n" + "═" * 100)
    print("E2E СИМУЛЯЦИЯ ЗАВЕРШЕНА УСПЕШНО")
    print("═" * 100)


if __name__ == "__main__":
    asyncio.run(main())
