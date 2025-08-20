import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.bot.routers import callbacks as callbacks_router
from app.bot.routers import commands as commands_router

def build_bot_and_dispatcher():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    bot = Bot(token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    dp.include_router(commands_router.router)
    dp.include_router(callbacks_router.router)
    return bot, dp
