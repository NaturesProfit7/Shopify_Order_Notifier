# app/services/status_ui.py
from app.models import OrderStatus

def status_title(status: OrderStatus) -> str:
    return {
        OrderStatus.NEW: "Новий",
        OrderStatus.WAITING_PAYMENT: "Очікує оплату",
        OrderStatus.PAID: "Оплачено",
        OrderStatus.CANCELLED: "Скасовано",
    }[status]

def buttons_for_status(status: OrderStatus, order_id: int):
    """Возвращает inline_keyboard в виде list[list[dict]] для Telegram HTTP API."""
    if status == OrderStatus.NEW:
        return [[
            {"text": "Зв’язались", "callback_data": f"order:{order_id}:set:WAITING_PAYMENT"},
            {"text": "Скасування", "callback_data": f"order:{order_id}:set:CANCELLED"},
        ]]
    if status == OrderStatus.WAITING_PAYMENT:
        return [[
            {"text": "Оплатили", "callback_data": f"order:{order_id}:set:PAID"},
            {"text": "Скасування", "callback_data": f"order:{order_id}:set:CANCELLED"},
        ]]
    # в конечных статусах — без кнопок
    return []
