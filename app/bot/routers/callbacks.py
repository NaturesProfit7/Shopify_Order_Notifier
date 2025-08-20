import asyncio

from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.db import get_session
from app.models import Order, OrderStatus
from app.services.menu_ui import order_card_buttons
from app.services.status_ui import status_title
from app.bot.services.message_builder import build_order_message
from app.bot.texts import build_manager_message  # см. ниже "texts.py" (быстрая версия внутри этого файла)
from app.services.tg_service import edit_message_text, send_text_with_buttons

router = Router()

def _parse_cbdata(data: str):
    # ожидаем: order:<id>:set:<STATUS>
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "order" or parts[2] != "set":
        return None, None
    return int(parts[1]), parts[3]

@router.callback_query(F.data.regexp(r"^order:\d+:view$"))
async def on_order_view_click(cb: CallbackQuery):
    order_id = int(cb.data.split(":")[1])
    with get_session() as s:
        order = s.get(Order, order_id)
        if not order:
            await cb.answer("Замовлення не знайдено", show_alert=False)
            return
        message_text = build_order_message(order, detailed=True)
        buttons = order_card_buttons(order.id)

    result = send_text_with_buttons(message_text, buttons)
    if asyncio.iscoroutine(result):
        await result
    await cb.answer()


@router.callback_query(F.data.regexp(r"^order:\d+:set:"))
async def on_order_status_click(cb: CallbackQuery):
    order_id, status_str = _parse_cbdata(cb.data)
    if not order_id or not status_str:
        await cb.answer("Некоректні дані", show_alert=False)
        return

    try:
        new_status = OrderStatus(status_str)
    except Exception:
        await cb.answer("Некоректний статус", show_alert=False)
        return

    chat_id = str(cb.message.chat.id) if cb.message else None
    message_id = cb.message.message_id if cb.message else None

    with get_session() as s:
        db = s.get(Order, order_id)
        if not db:
            await cb.answer("Замовлення не знайдено", show_alert=False)
            return
        db.status = new_status
        new_text = build_manager_message(db.raw_json or {}, new_status)

    await cb.answer(f"Статус → {status_title(new_status)}")
    if chat_id and message_id:
        edit_message_text(chat_id, message_id, new_text)  # клавиши пересоберёт твой main при новых событиях
