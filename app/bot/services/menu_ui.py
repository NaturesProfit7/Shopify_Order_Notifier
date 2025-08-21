# app/services/menu_ui.py
# DEPRECATED: Этот файл оставлен для обратной совместимости
# Вся логика меню перенесена в app/bot/routers/callbacks.py

from typing import List

Button = dict


def main_menu_buttons() -> List[List[Button]]:
    """DEPRECATED - используйте callback handlers"""
    return []


def orders_list_buttons(kind: str, offset: int, page_size: int,
                        has_prev: bool, has_next: bool) -> List[List[Button]]:
    """DEPRECATED - используйте callback handlers"""
    return []


def order_card_buttons(order_id: int) -> List[List[Button]]:
    """DEPRECATED - используйте callback handlers"""
    return []