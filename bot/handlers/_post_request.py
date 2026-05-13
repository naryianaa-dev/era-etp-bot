"""Общая пост-фиксация заявки: благодарность → графика → пауза → перезапуск.

Используется ветками ``car``/``parts``/``shop`` после того, как
:class:`bot.db.Request` записана и админам отправлено уведомление.

UX-сценарий (заданный пользователем):
  1. Бот отвечает текстовым «спасибо» с реквизитами заявки и фразой
     «Менеджер вернётся к вам с предложением в ближайшее время».
     **Без inline-меню** — клиент в этот момент ничего не выбирает.
  2. Шлёт графику ``ЗАКАЗ ПРИНЯТ В РАБОТУ`` (см. ``utils.order_accepted``).
  3. Ждёт 5 секунд — клиент успевает прочитать/проникнуться.
  4. «Перезапускает» бота: подкладывает persistent reply-клавиатуру
     ``🚀 Начать`` и заново показывает главное inline-меню, чтобы
     можно было сразу оформить следующую заявку.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from ..keyboards import main_menu, welcome_reply_kb
from ..utils.order_accepted import make_order_accepted_png

log = logging.getLogger(__name__)


_AFTER_ORDER_PAUSE_SEC = 5
"""Сколько секунд держать клиента на «галочке» перед перезапуском."""

_THANKS_LINE = (
    "🙏 <b>Спасибо за заявку!</b>\n\n"
    "Менеджер вернётся к вам с предложением в ближайшее время."
)


async def finish_request_accepted(
    *,
    bot: Bot,
    chat_id: int,
    request_id: int,
    summary_html: str,
) -> None:
    """Послать «спасибо + детали + графика + пауза + перезапуск».

    ``summary_html`` — уже **HTML-экранированный** блок про заявку
    (товар/ссылка/VIN/артикул и т.п.), как раньше шёл в тексте «Заявка
    принята». Заголовок «✅ Заявка #N принята» добавляется внутри.
    """
    # 1. Текстовое «спасибо» с реквизитами заявки. БЕЗ inline-меню.
    text = (
        f"✅ <b>Заявка #{request_id} принята.</b>\n\n"
        f"{summary_html}\n"
        f"{_THANKS_LINE}"
    )
    try:
        await bot.send_message(chat_id, text)
    except Exception as e:  # noqa: BLE001
        log.warning("finish_request_accepted: не удалось послать текст: %s", e)

    # 2. Графика «ЗАКАЗ ПРИНЯТ В РАБОТУ».
    try:
        png = make_order_accepted_png(request_id)
        await bot.send_photo(
            chat_id,
            BufferedInputFile(png, filename=f"order_{request_id}.png"),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("finish_request_accepted: не удалось сгенерировать/послать графику: %s", e)

    # 3. Пауза 5 сек — клиент читает картинку.
    await asyncio.sleep(_AFTER_ORDER_PAUSE_SEC)

    # 4. «Перезапуск»: persistent reply-клавиатура снизу + главное меню сверху.
    try:
        await bot.send_message(
            chat_id,
            "👋",
            reply_markup=welcome_reply_kb(),
        )
        await bot.send_message(
            chat_id,
            "📍 Главное меню — выбери, что сделать дальше:",
            reply_markup=main_menu(),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("finish_request_accepted: не удалось показать главное меню: %s", e)


async def finish_request_accepted_for_message(
    message: Message, *, request_id: int, summary_html: str
) -> None:
    """Хелпер для веток, которые финалят запрос из ``Message``-хендлера."""
    if message.bot is None or message.chat is None:
        return
    await finish_request_accepted(
        bot=message.bot,
        chat_id=message.chat.id,
        request_id=request_id,
        summary_html=summary_html,
    )


async def finish_request_accepted_for_cb(
    cb: CallbackQuery, *, request_id: int, summary_html: str
) -> None:
    """Хелпер для веток, которые финалят запрос из ``CallbackQuery``-хендлера.

    Перед стартом сценария убираем inline-кнопки с того сообщения,
    из которого пришёл callback (обычно это последний шаг выбора —
    например, «способ оплаты» в ветке авто). Если кнопок там нет
    или их уже сняли — игнорируем.
    """
    if cb.bot is None or cb.message is None or cb.message.chat is None:
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await finish_request_accepted(
        bot=cb.bot,
        chat_id=cb.message.chat.id,
        request_id=request_id,
        summary_html=summary_html,
    )
