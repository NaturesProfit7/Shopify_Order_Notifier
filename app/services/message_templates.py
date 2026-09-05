# app/services/message_templates.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
from __future__ import annotations
from jinja2 import Template

from app.services.order_fields import get_customer_given_name, get_payment_info

# Текст, который менеджер пересылает клиенту вместе с PDF
CLIENT_ORDER_ACCEPTED = Template(
    (
        "Вітаю, {{ first_name or 'клієнте' }} ☺️\n"
        "Отримали ваше замовлення №{{ order_number }}\n"
        "{% if payment_line %}{{ payment_line }}\n{% endif %}"
        "\n"
        "Максимальний термін виготовлення складає 7 днів, "
        "одразу по готовності відправляємо замовлення вам\n"
        "Передаємо в роботу, мирного дня 🙏"
    )
)


def _client_payment_line(order: dict) -> str:
    """«Статус оплати: повна передоплата» / «... часткова передоплата (200.00 грн)».

    Для статусов, отличных от paid/partially_paid (возврат, ожидание),
    строку клиенту не показываем.
    """
    info = get_payment_info(order)

    if info["status"] == "paid":
        return "Статус оплати: повна передоплата"

    if info["is_partial"]:
        if info["paid"] is not None:
            return f"Статус оплати: часткова передоплата ({info['paid']:.2f} грн)"
        return "Статус оплати: часткова передоплата"

    return ""


def render_client_order_accepted(order: dict) -> str:
    """Сообщение клиенту, которое уходит подписью к PDF."""
    return CLIENT_ORDER_ACCEPTED.render(
        first_name=get_customer_given_name(order),
        order_number=order.get("order_number") or order.get("id"),
        payment_line=_client_payment_line(order),
    )

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