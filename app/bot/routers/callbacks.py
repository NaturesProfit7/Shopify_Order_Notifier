import asyncio

from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.db import get_session
from app.models import Order, OrderStatus
from app.services.menu_ui import (
    order_card_buttons,
    orders_list_buttons,
    main_menu_buttons,
)
from app.services.status_ui import status_title
from app.bot.services.message_builder import build_order_message
from app.bot.texts import (
    build_manager_message,
)  # см. ниже "texts.py" (быстрая версия внутри этого файла)

from app.bot.services.message_builder import get_status_emoji
from app.services.tg_service import edit_message_text, send_text_with_buttons

router = Router()


def _parse_cbdata(data: str):
    # ожидаем: order:<id>:set:<STATUS>
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "order" or parts[2] != "set":
        return None, None
    try:
        order_id = int(parts[1])
    except ValueError:
        return None, None
    return order_id, parts[3]


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
    if order_id is None or status_str is None:
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
        edit_message_text(
            chat_id, message_id, new_text
        )  # клавиши пересоберёт твой main при новых событиях


@router.callback_query(F.data == "menu:main")
async def on_main_menu_click(cb: CallbackQuery):
    """Return to the main menu."""
    result = send_text_with_buttons("Главное меню", main_menu_buttons())
    if asyncio.iscoroutine(result):
        await result
    await cb.answer()


def _parse_orders_list_data(data: str):
    """Parse callback data for orders list.

    Expected format: orders:list:<kind>:offset=<n>
    Returns tuple(kind, offset) or (None, None) if invalid.
    """
    parts = data.split(":")
    if (
        len(parts) != 4
        or parts[0] != "orders"
        or parts[1] != "list"
        or not parts[3].startswith("offset=")
    ):
        return None, None
    kind = parts[2]
    try:
        offset = int(parts[3].split("=", 1)[1])
    except ValueError:
        offset = 0
    return kind, max(offset, 0)


@router.callback_query(F.data.startswith("orders:list:"))
async def on_orders_list_click(cb: CallbackQuery):
    """Show list of orders with pagination."""
    kind, offset = _parse_orders_list_data(cb.data)
    if kind is None:
        await cb.answer("Некоректні дані", show_alert=False)
        return

    PAGE_SIZE = 10
    with get_session() as s:
        query = s.query(Order)
        if kind == "pending":
            query = query.filter(Order.status == OrderStatus.NEW)

        total = query.count()

        orders = (
            query.order_by(Order.created_at.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
            .all()
        )

        lines: list[str] = []
        buttons: list[list[dict]] = []
        for order in orders:
            order_no = order.order_number or order.id
            customer = (
                f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip()
                or "Без імені"
            )
            emoji = get_status_emoji(order.status)
            lines.append(f"• №{order_no} - {customer} {emoji}")
            buttons.append(
                [{"text": f"№{order_no}", "callback_data": f"order:{order.id}:view"}]
            )

    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    current_page = min(offset // PAGE_SIZE + 1, total_pages)
    has_prev = offset > 0
    has_next = offset + PAGE_SIZE < total

    # Pagination buttons
    buttons.extend(
        orders_list_buttons(
            kind,
            offset,
            PAGE_SIZE,
            has_prev=has_prev,
            has_next=has_next,
        )
    )

    text = f"Список замовлень ({kind}) {current_page}/{total_pages}"
    if lines:
        text += "\n\n" + "\n".join(lines)
    else:
        text += "\n\nНемає замовлень"

    result = send_text_with_buttons(text, buttons)
    if asyncio.iscoroutine(result):
        await result
    await cb.answer()
