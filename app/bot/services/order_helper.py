# app/bot/services/order_helper.py
"""Helper функции для работы с заказами"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.models import Order, OrderStatus


def build_enhanced_order_message(order: Order, order_data: dict) -> str:
    """Построить улучшенное сообщение о заказе"""
    order_no = order.order_number or order.id
    status_emoji = "🆕"

    # Имя клиента
    customer_name = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"

    # Телефон БЕЗ пробелов
    phone = order.customer_phone_e164 if order.customer_phone_e164 else "Не вказано"

    message = f"""📦 <b>Замовлення #{order_no}</b> • {status_emoji} Новий
━━━━━━━━━━━━━━━━━━━━━━
👤 {customer_name}
📱 {phone}"""

    # Товары
    items = order_data.get("line_items", [])
    if items:
        message += "\n━━━━━━━━━━━━━━━━━━━━━━\n🛍 <b>Товари:</b>"
        for item in items[:3]:  # Показываем первые 3
            title = item.get("title", "")
            qty = item.get("quantity", 0)
            price = float(item.get("price", 0))
            message += f"\n• {title} x{qty} - {price:.2f} UAH"

        if len(items) > 3:
            message += f"\n<i>...та ще {len(items) - 3} товарів</i>"

    # Доставка
    shipping = order_data.get("shipping_address", {})
    if shipping:
        city = shipping.get("city", "")
        address = shipping.get("address1", "")
        if city or address:
            delivery_parts = [p for p in [city, address] if p]
            message += f"\n📍 <b>Доставка:</b> {', '.join(delivery_parts)}"

    # Сумма
    total = order_data.get("total_price", "")
    currency = order_data.get("currency", "UAH")
    if total:
        message += f"\n💰 <b>Сума:</b> {total} {currency}"

    return message


def get_enhanced_order_keyboard(order: Order) -> InlineKeyboardMarkup:
    """Клавиатура для основного сообщения заказа - ЕДИНЫЙ ФОРМАТ"""
    buttons = []

    # Первый ряд: Кнопки статуса
    if order.status == OrderStatus.NEW:
        buttons.append([
            InlineKeyboardButton(text="✅ Зв'язались", callback_data=f"order:{order.id}:contacted"),
            InlineKeyboardButton(text="❌ Скасування", callback_data=f"order:{order.id}:cancel")
        ])
    elif order.status == OrderStatus.WAITING_PAYMENT:
        buttons.append([
            InlineKeyboardButton(text="💰 Оплатили", callback_data=f"order:{order.id}:paid"),
            InlineKeyboardButton(text="❌ Скасування", callback_data=f"order:{order.id}:cancel")
        ])
    elif order.status == OrderStatus.PAID:
        # Для оплаченных заказов только файлы и доп действия
        pass
    elif order.status == OrderStatus.CANCELLED:
        # Для отмененных заказов только файлы
        pass

    # Второй ряд: Файлы PDF и VCF
    buttons.append([
        InlineKeyboardButton(text="📄 PDF", callback_data=f"order:{order.id}:resend:pdf"),
        InlineKeyboardButton(text="📱 VCF", callback_data=f"order:{order.id}:resend:vcf")
    ])

    # Третий ряд: Реквизиты (на всю ширину)
    buttons.append([
        InlineKeyboardButton(text="💳 Реквізити", callback_data=f"order:{order.id}:payment")
    ])

    # Четвертый ряд: Дополнительные действия (для активных заказов)
    if order.status in [OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]:
        buttons.append([
            InlineKeyboardButton(text="💬 Коментар", callback_data=f"order:{order.id}:comment"),
            InlineKeyboardButton(text="⏰ Нагадати", callback_data=f"order:{order.id}:reminder")
        ])

    # Пятый ряд: Навигация
    buttons.append([
        InlineKeyboardButton(text="↩️ До списку", callback_data=f"orders:list:pending:offset=0")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)