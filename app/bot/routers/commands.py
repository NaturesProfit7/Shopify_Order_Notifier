from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()

@router.message(CommandStart())
async def on_start(msg: Message):
    await msg.answer("Бот активен. Жмите кнопки под заказами 😉")
