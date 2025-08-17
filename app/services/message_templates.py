from __future__ import annotations
from jinja2 import Template

# Базовый UA-шаблон подтверждения
CONFIRM_UA = Template(
    (
        "Вітаю, {{ first_name or 'клієнте' }}! ☺️\n"
        "Ваше замовлення №{{ order_number }} прийнято.\n"
        "{% if items %}Склад: {{ items }}.\n{% endif %}"
        "Все вірно?\n"
        "Як зручно підтвердити/уточнити — тут у Telegram.\n"
    )
)

def render_confirm(order: dict) -> str:
    order_number = order.get("order_number") or order.get("id")
    first_name = ((order.get("customer") or {}).get("first_name") or
                  (order.get("shipping_address") or {}).get("first_name") or "")
    # компактный список товаров
    titles = []
    for it in (order.get("line_items") or []):
        title = str(it.get("title") or "").strip()
        qty = int(it.get("quantity") or 0)
        titles.append(f"{title} ×{qty}" if qty else title)
    items_str = ", ".join(titles[:5])  # для начала ограничим до 5 позиций
    return CONFIRM_UA.render(first_name=first_name, order_number=order_number, items=items_str)
