# app/services/message_templates.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
from __future__ import annotations
from jinja2 import Template

# Простой UA-шаблон подтверждения (без деталей)
SIMPLE_CONFIRM = Template(
    (
        "Вітаю, {{ first_name or 'клієнте' }} ☺️\n"
        "Ваше замовлення №{{ order_number }}\n"
        "Все вірно?"
    )
)


def render_simple_confirm_with_contact(order: dict, contact_first_name: str, contact_last_name: str) -> str:
    """
    НОВАЯ ФУНКЦИЯ: Возвращает минимальный текст с явно указанным контактным именем:
      Вітаю, <contact_first_name> ☺️
      Ваше замовлення №<order_number>
      Все вірно?
    """
    order_number = order.get("order_number") or order.get("id")

    return SIMPLE_CONFIRM.render(
        first_name=(contact_first_name or "").strip(),
        order_number=order_number,
    )


def render_simple_confirm(order: dict) -> str:
    """
    СТАРАЯ ФУНКЦИЯ: Возвращает минимальный текст (для обратной совместимости):
      Вітаю, <ім'я> ☺️
      Ваше замовлення №<order_number>
      Все вірно?
    """
    order_number = order.get("order_number") or order.get("id")
    first_name = (
            ((order.get("customer") or {}).get("first_name"))
            or ((order.get("shipping_address") or {}).get("first_name"))
            or ((order.get("billing_address") or {}).get("first_name"))
            or ""
    )
    return SIMPLE_CONFIRM.render(
        first_name=(first_name or "").strip(),
        order_number=order_number,
    )