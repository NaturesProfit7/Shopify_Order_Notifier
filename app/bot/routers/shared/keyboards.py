# app/bot/routers/shared/keyboards.py - РАБОЧАЯ ВЕРСИЯ
"""Клавиатуры для бота"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.models import Order, OrderStatus


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    buttons = [
        [InlineKeyboardButton(text="📋 Необроблені", callback_data="orders:list:new:offset=0")],
        [InlineKeyboardButton(text="💳 Очікують оплати", callback_data="orders:list:waiting:offset=0")],
        [InlineKeyboardButton(text="📦 Всі замовлення", callback_data="orders:list:all:offset=0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def stats_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура статистики"""
    buttons = [[
        InlineKeyboardButton(text="🔄 Оновити", callback_data="stats:refresh"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main")
    ]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню"""
    buttons = [[
        InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu:main")
    ]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def orders_list_keyboard(kind: str, offset: int, page_size: int,
                         total: int, has_orders: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура для списка заказов с пагинацией"""
    buttons = []

    if has_orders:
        nav_buttons = []
        if offset > 0:
            nav_buttons.append(
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"orders:list:{kind}:offset={offset - page_size}")
            )

        current_page = (offset // page_size) + 1
        total_pages = (total + page_size - 1) // page_size
        nav_buttons.append(
            InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="noop")
        )

        if offset + page_size < total:
            nav_buttons.append(
                InlineKeyboardButton(text="Вперед ➡️", callback_data=f"orders:list:{kind}:offset={offset + page_size}")
            )

        if nav_buttons:
            buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu:main")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def order_card_keyboard(order: Order) -> InlineKeyboardMarkup:
    """Клавиатура для карточки заказа - ПРОСТАЯ РАБОЧАЯ ВЕРСИЯ"""
    buttons = []

    # Кнопки статуса
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

    # Файлы
    buttons.append([
        InlineKeyboardButton(text="📄 PDF", callback_data=f"order:{order.id}:resend:pdf"),
        InlineKeyboardButton(text="📱 VCF", callback_data=f"order:{order.id}:resend:vcf")
    ])

    # Реквизиты
    buttons.append([
        InlineKeyboardButton(text="💳 Реквізити", callback_data=f"order:{order.id}:payment")
    ])

    # Кнопка покупця — для всіх статусів
    buyer_id = (order.raw_json or {}).get("_crm_buyer_id")
    if buyer_id:
        buttons.append([
            InlineKeyboardButton(text="✅ Покупець в CRM", callback_data="noop")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="👤 Створити покупця", callback_data=f"order:{order.id}:create_buyer")
        ])

    # CRM-кнопка для оплачених замовлень
    if order.status == OrderStatus.PAID:
        crm_id = (order.raw_json or {}).get("_crm_order_id")
        if crm_id:
            buttons.append([
                InlineKeyboardButton(text="✅ Замовлення в CRM", callback_data="noop")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(text="🏪 Створити замовлення", callback_data=f"order:{order.id}:create_crm")
            ])

    # Дополнительные действия
    if order.status in [OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]:
        buttons.append([
            InlineKeyboardButton(text="💬 Коментар", callback_data=f"order:{order.id}:comment"),
            InlineKeyboardButton(text="⏰ Нагадати", callback_data=f"order:{order.id}:reminder")
        ])

    # Навигация
    buttons.append([
        InlineKeyboardButton(text="↩️ До списку", callback_data=f"order:{order.id}:back_to_list")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def reminder_time_keyboard(order_id: int) -> InlineKeyboardMarkup:
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
            InlineKeyboardButton(text="↩️ Назад", callback_data=f"order:{order_id}:back_to_list")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)