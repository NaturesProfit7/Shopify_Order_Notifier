# app/bot/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.models import Order, OrderStatus


def get_order_keyboard(order: Order) -> InlineKeyboardMarkup:
    """Генерация клавиатуры в зависимости от статуса заказа"""
    buttons = []

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
        # Для оплаченных заказов кнопок нет, только эмодзи в тексте
        pass
    elif order.status == OrderStatus.CANCELLED:
        # Для отмененных заказов кнопок нет
        pass

    # Дополнительные кнопки доступны для активных заказов
    if order.status in [OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]:
        buttons.append([
            InlineKeyboardButton(text="💬 Коментар", callback_data=f"order:{order.id}:comment"),
            InlineKeyboardButton(text="⏰ Нагадати", callback_data=f"order:{order.id}:reminder")
        ])

    # Кнопка для показа деталей всегда доступна
    buttons.append([
        InlineKeyboardButton(text="📋 Деталі", callback_data=f"order:{order.id}:show")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_reminder_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Клавиатура выбора времени напоминания"""
    buttons = [
        [
            InlineKeyboardButton(text="15 хв", callback_data=f"reminder:{order_id}:15"),
            InlineKeyboardButton(text="30 хв", callback_data=f"reminder:{order_id}:30"),
            InlineKeyboardButton(text="1 год", callback_data=f"reminder:{order_id}:60")
        ],
        [
            InlineKeyboardButton(text="2 год", callback_data=f"reminder:{order_id}:120"),
            InlineKeyboardButton(text="4 год", callback_data=f"reminder:{order_id}:240"),
            InlineKeyboardButton(text="Завтра", callback_data=f"reminder:{order_id}:1440")
        ],
        [
            InlineKeyboardButton(text="↩️ Назад", callback_data=f"order:{order_id}:back")
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)