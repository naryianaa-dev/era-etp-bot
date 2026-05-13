"""Точка входа бота — long polling."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import get_settings
from .db import init_db
from .handlers import get_main_router


BOT_DESCRIPTION = (
    "ERA ETP — площадка под ключ: автомобили, запчасти, покупки.\n\n"
    "Как это работает:\n"
    "1) Создаёшь заявку в боте (марка/модель/бюджет — или просто ссылка на товар).\n"
    "2) Менеджер пришлёт оффер с финальной ценой.\n"
    "3) Оплата через СБП в один тап — кнопка прямо в чате.\n"
    "4) Закрывающие документы (УПД/счёт-фактура) приходят на e-mail после "
    "поступления оплаты на расчётный счёт ООО «Форсаж».\n\n"
    "Жми «Начать», чтобы оформить первую заявку."
)
BOT_SHORT_DESCRIPTION = (
    "Подбор авто, запчастей и покупок под ключ. Оплата СБП, УПД на e-mail."
)


async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    logging.info("Бот @%s запущен. id=%s", me.username, me.id)
    # проставим список команд в меню Telegram
    from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

    user_commands = [
        BotCommand(command="start", description="Начать работу"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="cancel", description="Отменить текущее действие"),
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    admin_commands = user_commands + [
        BotCommand(command="inbox", description="Все входящие заявки"),
        BotCommand(command="inbox_new", description="Только необработанные"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="offer", description="Создать оффер (тег id_юзера)"),
    ]
    for admin_id in get_settings().admin_ids:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            logging.warning("Не удалось выставить команды для админа %s: %s", admin_id, e)

    # Описание (видно на profile-странице бота, над кнопкой START для
    # новых пользователей) + короткое описание (видно в превью бота).
    # Telegram кэширует значения — set_my_* идемпотентны.
    try:
        await bot.set_my_description(description=BOT_DESCRIPTION)
    except Exception as e:
        logging.warning("Не удалось установить description: %s", e)
    try:
        await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
    except Exception as e:
        logging.warning("Не удалось установить short_description: %s", e)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(get_main_router())
    dp.startup.register(on_startup)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("bot stopped", file=sys.stderr)
