from typing import Literal, List


Button = dict


def main_menu_buttons() -> List[List[Button]]:
    """Главное меню"""
    return [
        [{"text": "📋 Необработанные", "callback_data": "orders:list:pending:offset=0"}],
        [{"text": "📦 Все заказы", "callback_data": "orders:list:all:offset=0"}],
    ]


def orders_list_buttons(kind: Literal["pending", "all"], offset: int, page_size: int) -> List[List[Button]]:
    """Кнопки пагинации списка заказов"""
    prev_offset = max(offset - page_size, 0)
    next_offset = offset + page_size
    return [
        [
            {"text": "⬅️", "callback_data": f"orders:list:{kind}:offset={prev_offset}"},
            {"text": "➡️", "callback_data": f"orders:list:{kind}:offset={next_offset}"},
        ],
        [{"text": "🏠 Главное меню", "callback_data": "menu:main"}],
    ]


def order_actions_buttons(order_id: int) -> List[List[Button]]:
    """Кнопки действий с заказом"""
    return [
        [
            {"text": "PDF", "callback_data": f"order:{order_id}:resend:pdf"},
            {"text": "VCF", "callback_data": f"order:{order_id}:resend:vcf"},
        ]
    ]


def order_card_buttons(order_id: int) -> List[List[Button]]:
    """Кнопки в карточке заказа"""
    buttons = order_actions_buttons(order_id)
    buttons.append([{ "text": "Назад", "callback_data": "orders:list:pending:offset=0" }])
    buttons.append([{ "text": "🏠 Главное меню", "callback_data": "menu:main" }])
    return buttons

