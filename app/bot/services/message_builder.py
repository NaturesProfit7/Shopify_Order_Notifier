# app/bot/services/message_builder.py
from app.models import Order, OrderStatus
from app.services.order_fields import build_delivery_short, format_money, get_payment_info

# Using a simple hyphen line avoids rendering issues across devices
DIVIDER = "-" * 5


def build_payment_line(raw_json: dict | None) -> str | None:
    """Строка статуса оплаты Shopify для карточки заказа.

    💳 <b>Статус оплати:</b> Частково сплачено • передоплата 200.00 UAH
    Возвращает None, если Shopify не прислал понятный financial_status.
    """
    if not raw_json:
        return None

    info = get_payment_info(raw_json)
    if not info["label"]:
        return None

    line = f"💳 <b>Статус оплати:</b> {info['label']}"
    if info["is_partial"] and info["paid"] is not None:
        line += f" • передоплата {format_money(info['paid'], info['currency'])}"
    return line


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


def format_phone_compact(e164: str) -> str:
    """Форматирует телефон компактно без пробелов"""
    if not e164:
        return "Не вказано"
    return e164  # Просто E.164 без изменений: +380960790247


def build_order_message(order: Order, detailed: bool = False) -> str:
    """
    Построить сообщение о заказе в едином формате.
    Используется как для новых заказов, так и для карточек из списка.
    """
    order_no = order.order_number or order.id
    status_emoji = get_status_emoji(order.status)
    status_text = get_status_text(order.status)

    # Имя клиента
    customer_name = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"

    # Телефон БЕЗ пробелов
    phone = format_phone_compact(order.customer_phone_e164)

    # Основное сообщение
    message = f"""📦 <b>Замовлення #{order_no}</b> • {status_emoji} {status_text}
{DIVIDER}
👤 {customer_name}
📱 {phone}"""

    # Детальная информация (если запрошено и есть данные)
    if detailed and order.raw_json:
        data = order.raw_json

        message += f"\n{DIVIDER}"

        # Товары
        items = data.get("line_items", [])
        if items:
            message += "\n🛍 <b>Товари:</b>"
            total_sum = 0
            for item in items[:5]:  # Показываем первые 5
                title = item.get("title", "")
                qty = item.get("quantity", 0)
                price = float(item.get("price", 0))
                total_sum += price * qty
                message += f"\n• {title} x{qty} - {price:.2f} UAH"

            if len(items) > 5:
                message += f"\n<i>...та ще {len(items) - 5} товарів</i>"

        # Доставка
        delivery = build_delivery_short(data)
        if delivery:
            message += f"\n📍 <b>Доставка:</b> {delivery}"

        # Сумма
        total = data.get("total_price", "")
        currency = data.get("currency", "UAH")
        if total:
            message += f"\n💰 <b>Сума:</b> {total} {currency}"

        # Статус оплаты Shopify
        payment_line = build_payment_line(data)
        if payment_line:
            message += f"\n{payment_line}"

    # Дополнительная информация (если есть)
    if order.comment or order.reminder_at or order.processed_by_username:
        message += f"\n{DIVIDER}"

        if order.comment:
            message += f"\n💬 <i>Коментар: {order.comment}</i>"

        if order.reminder_at:
            reminder_time = order.reminder_at.strftime("%d.%m %H:%M")
            message += f"\n⏰ <i>Нагадування: {reminder_time}</i>"

        if order.processed_by_username:
            message += f"\n👨‍💼 <i>Менеджер: @{order.processed_by_username}</i>"

    return message
