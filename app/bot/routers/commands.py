from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.services.menu_ui import main_menu_buttons
from app.services.tg_service import send_text_with_buttons

router = Router()

@router.message(CommandStart())
async def on_start(msg: Message):
    await msg.answer("Бот активен. Жмите кнопки под заказами 😉")


@router.message(Command("menu"))
async def on_menu(msg: Message):
    send_text_with_buttons("Главное меню", main_menu_buttons())
