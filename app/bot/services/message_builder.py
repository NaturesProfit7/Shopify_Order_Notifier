# app/bot/services/message_builder.py
from app.models import Order, OrderStatus
from app.services.phone_utils import pretty_ua_phone


def get_status_emoji(status: OrderStatus) -> str:
    """Получить эмодзи для статуса"""
    return {
        OrderStatus.NEW: "🆕",
        OrderStatus.WAITING_PAYMENT: "⏳",
        OrderStatus.PAID: "✅",
        OrderStatus.CANCELLED: "❌"
    }[status]


def get_status_text(status: OrderStatus) -> str:
    """Получить текст статуса"""
    return {
        OrderStatus.NEW: "Новий",
        OrderStatus.WAITING_PAYMENT: "Очікує оплату",
        OrderStatus.PAID: "Оплачено",
        OrderStatus.CANCELLED: "Скасовано"
    }[status]


def build_order_message(order: Order, detailed: bool = False) -> str:
    """Построить сообщение о заказе"""

    order_no = order.order_number or order.id
    status_emoji = get_status_emoji(order.status)
    status_text = get_status_text(order.status)

    # Имя клиента
    customer_name = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"

    # Телефон
    phone = pretty_ua_phone(order.customer_phone_e164) if order.customer_phone_e164 else "Не вказано"

    # Основное сообщение
    message = f"""
📦 <b>Замовлення #{order_no}</b> • {status_emoji} {status_text}
━━━━━━━━━━━━━━━━━━━━━━
👤 <b>{customer_name}</b>
📱 {phone}
"""

    # Если есть комментарий
    if order.comment:
        message += f"\n💬 <i>Коментар: {order.comment}</i>\n"

    # Если установлено напоминание
    if order.reminder_at:
        from datetime import datetime
        reminder_time = order.reminder_at.strftime("%d.%m %H:%M")
        message += f"\n⏰ <i>Нагадування: {reminder_time}</i>\n"

    # Сообщение для клиента
    message += f"""
━━━━━━━━━━━━━━━━━━━━━━
💬 <b>Повідомлення клієнту:</b>
<i>Вітаю, {order.customer_first_name or 'клієнте'} ☺️
Ваше замовлення №{order_no}
Все вірно?</i>
"""

    # Если нужна детальная информация
    if detailed and order.raw_json:
        data = order.raw_json

        # Товары
        items = data.get("line_items", [])
        if items:
            message += "\n━━━━━━━━━━━━━━━━━━━━━━\n🛍 <b>Товари:</b>\n"
            for item in items[:5]:  # Показываем первые 5
                title = item.get("title", "")
                qty = item.get("quantity", 0)
                price = item.get("price", "0")
                message += f"• {title} x{qty} - {price} UAH\n"
            if len(items) > 5:
                message += f"<i>...та ще {len(items) - 5} товарів</i>\n"

        # Доставка
        shipping = data.get("shipping_address", {})
        if shipping:
            city = shipping.get("city", "")
            address = shipping.get("address1", "")
            if city or address:
                message += f"\n📍 <b>Доставка:</b> {city}, {address}\n"

        # Сумма
        total = data.get("total_price", "")
        if total:
            message += f"\n💰 <b>Сума:</b> {total} UAH\n"

    # Информация о менеджере
    if order.processed_by_username:
        message += f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
        message += f"👨‍💼 Менеджер: @{order.processed_by_username}\n"
        if order.updated_at:
            update_time = order.updated_at.strftime("%d.%m %H:%M")
            message += f"🕐 Оновлено: {update_time}\n"

    return message