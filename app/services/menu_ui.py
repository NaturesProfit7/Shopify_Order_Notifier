from typing import Literal, List


Button = dict


def main_menu_buttons() -> List[List[Button]]:
    """Главное меню"""
    return [
        [{"text": "📋 Необработанные", "callback_data": "orders:list:pending:offset=0"}],
        [{"text": "📦 Все заказы", "callback_data": "orders:list:all:offset=0"}],
    ]


def orders_list_buttons(
    kind: Literal["pending", "all"],
    offset: int,
    page_size: int,
    *,
    has_prev: bool,
    has_next: bool,
) -> List[List[Button]]:
    """Кнопки пагинации списка заказов"""
    buttons: List[List[Button]] = []
    nav_row: List[Button] = []

    if has_prev:
        prev_offset = max(offset - page_size, 0)
        nav_row.append(
            {"text": "⬅️", "callback_data": f"orders:list:{kind}:offset={prev_offset}"}
        )
    if has_next:
        next_offset = offset + page_size
        nav_row.append(
            {"text": "➡️", "callback_data": f"orders:list:{kind}:offset={next_offset}"}
        )

    if nav_row:
        buttons.append(nav_row)

    buttons.append([{ "text": "🏠 Главное меню", "callback_data": "menu:main" }])
    return buttons


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

