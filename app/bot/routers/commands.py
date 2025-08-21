import asyncio

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.services.menu_ui import main_menu_buttons
from app.services.tg_service import send_text_with_buttons

router = Router()

@router.message(CommandStart())
async def on_start(msg: Message):
    await msg.answer("Бот активен. Жмите кнопки под заказами 😉")


@router.message(Command(commands=["menu"]))
async def on_menu(msg: Message):
    """Показать главное меню"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = [
        [InlineKeyboardButton(text="📋 Необроблені", callback_data="orders:list:pending:offset=0")],
        [InlineKeyboardButton(text="📦 Всі замовлення", callback_data="orders:list:all:offset=0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show")]
    ]

    await msg.answer(
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )