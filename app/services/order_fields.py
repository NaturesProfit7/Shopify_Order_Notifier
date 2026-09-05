# app/services/order_fields.py
"""Единая точка извлечения полей заказа с учётом платёжки Chekly.

Chekly кладёт всю полезную информацию в `note_attributes` заказа Shopify
(в админке — блок «Дополнительные сведения»), при этом:

* `shipping_lines` приходит пустым;
* `billing_address` = null;
* `shipping_address.first_name` / `last_name` идут в обратном порядке
  относительно `Recipient Name`.

Поэтому источником истины считаем `note_attributes`, а на старые заказы
(до подключения Chekly) остаётся fallback на `shipping_address` и
`app/services/address_utils.py`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.phone_utils import normalize_ua_phone, pretty_ua_phone

# Единственный способ доставки после подключения Chekly
DELIVERY_SERVICE = "Нова Пошта"

# financial_status Shopify → украинская подпись
PAYMENT_STATUS_UA: Dict[str, str] = {
    "paid": "Сплачено",
    "partially_paid": "Частково сплачено",
    "partially_refunded": "Частково повернено",
    "refunded": "Повернено",
    "voided": "Скасовано",
    "pending": "Очікує оплату",
    "authorized": "Очікує оплату",
}

# Имена note_attributes (Chekly)
NA_RECIPIENT_NAME = "Recipient Name"
NA_RECIPIENT_PHONE = "Recipient Phone"
NA_RECIPIENT_EMAIL = "Recipient Email"
NA_CUSTOMER_NAME = "Customer Name"
NA_CUSTOMER_PHONE = "Customer Phone"
NA_CUSTOMER_EMAIL = "Customer Email"
NA_CITY = "City"
NA_POST_OFFICE = "Post Office"
NA_ZIP = "_zip-code"
NA_COUNTRY = "_country"
NA_CHECKOUT_ID = "Checkout id"

_PARTIAL_PAYMENT_PREFIX = "partial payment value"


# ---------------------------------------------------------------------------
# note_attributes
# ---------------------------------------------------------------------------

def note_attributes(order: Dict[str, Any]) -> Dict[str, str]:
    """`note_attributes` заказа в виде {name: value}."""
    result: Dict[str, str] = {}
    for item in order.get("note_attributes") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result[name] = str(item.get("value") or "").strip()
    return result


def note_attr(order: Dict[str, Any], name: str) -> str:
    """Значение одного note_attribute (пустая строка, если нет)."""
    return note_attributes(order).get(name, "")


def is_chekly_order(order: Dict[str, Any]) -> bool:
    """Заказ оформлен через Chekly (есть его note_attributes)."""
    attrs = note_attributes(order)
    return bool(attrs.get(NA_RECIPIENT_NAME) or attrs.get(NA_CHECKOUT_ID))


def get_checkout_id(order: Dict[str, Any]) -> Optional[str]:
    """Checkout id платёжки — по нему ищем транзакцию в keyCRM."""
    return note_attr(order, NA_CHECKOUT_ID) or None


# ---------------------------------------------------------------------------
# Деньги
# ---------------------------------------------------------------------------

def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def get_currency(order: Dict[str, Any]) -> str:
    return (order.get("currency") or order.get("presentment_currency") or "UAH").upper()


def format_money(value: float, currency: str = "UAH") -> str:
    """200.0 → '200.00 UAH'. Без округления до целых (см. ТЗ)."""
    return f"{value:.2f} {currency}"


def _partial_payment_from_notes(order: Dict[str, Any]) -> Optional[float]:
    """Сумма из атрибута вида 'Partial payment value - Monobank' = '200 UAH'."""
    for name, value in note_attributes(order).items():
        if name.lower().startswith(_PARTIAL_PAYMENT_PREFIX):
            match = re.search(r"\d+(?:[.,]\d+)?", value)
            if match:
                return _to_float(match.group(0))
    return None


def get_payment_info(order: Dict[str, Any]) -> Dict[str, Any]:
    """Сводка по оплате заказа.

    Возвращает:
        status      — сырой financial_status Shopify
        label       — украинская подпись или None (тогда строку не выводим)
        is_partial  — частичная оплата
        total       — сумма заказа
        paid        — фактически оплачено (для частичной — сумма передоплаты)
        outstanding — остаток к оплате
        currency    — валюта
    """
    status = (order.get("financial_status") or "").strip().lower()
    currency = get_currency(order)

    total = _to_float(order.get("total_price"))
    if total is None:
        total = _to_float(order.get("current_total_price"))

    outstanding = _to_float(order.get("total_outstanding"))
    is_partial = status == "partially_paid"

    paid: Optional[float] = None
    if total is not None and outstanding is not None:
        paid = round(total - outstanding, 2)
    if is_partial and (paid is None or paid <= 0):
        paid = _partial_payment_from_notes(order)
        if paid is not None and total is not None:
            outstanding = round(total - paid, 2)
    if paid is None and status == "paid":
        paid = total
        outstanding = 0.0

    return {
        "status": status,
        "label": PAYMENT_STATUS_UA.get(status),
        "is_partial": is_partial,
        "total": total,
        "paid": paid,
        "outstanding": outstanding,
        "currency": currency,
    }


def build_payment_lines(order: Dict[str, Any]) -> List[str]:
    """Строки для PDF и CRM-комментария:

        Статус оплати: Частково сплачено
        Передоплата: 200.00 UAH
        Залишок: 350.00 UAH
    """
    info = get_payment_info(order)
    if not info["label"]:
        return []

    lines = [f"Статус оплати: {info['label']}"]
    if info["is_partial"]:
        if info["paid"] is not None:
            lines.append(f"Передоплата: {format_money(info['paid'], info['currency'])}")
        if info["outstanding"] is not None:
            lines.append(f"Залишок: {format_money(info['outstanding'], info['currency'])}")
    return lines


# ---------------------------------------------------------------------------
# Замовник и отримувач
# ---------------------------------------------------------------------------

def _normalize_name(value: str) -> str:
    return " ".join((value or "").split()).lower()


def _shipping_full_name(shipping: Dict[str, Any]) -> str:
    name = (shipping.get("name") or "").strip()
    if name:
        return name
    first = (shipping.get("first_name") or "").strip()
    last = (shipping.get("last_name") or "").strip()
    return f"{first} {last}".strip()


def get_parties(order: Dict[str, Any]) -> Dict[str, Any]:
    """Замовник и отримувач заказа.

    Возвращает {'customer': {...}, 'recipient': {...}, 'same': bool},
    где в каждом участнике — name / phone / phone_e164 / email.

    Для Chekly-заказов замовник берётся из `Customer *`; если этих
    атрибутов нет — замовник и есть отримувач.
    """
    attrs = note_attributes(order)
    shipping = order.get("shipping_address") or {}
    order_email = (order.get("email") or order.get("contact_email") or "").strip()

    recipient_name = attrs.get(NA_RECIPIENT_NAME) or _shipping_full_name(shipping)
    recipient_phone = attrs.get(NA_RECIPIENT_PHONE) or (shipping.get("phone") or "").strip()
    recipient_email = attrs.get(NA_RECIPIENT_EMAIL) or order_email

    customer_name = attrs.get(NA_CUSTOMER_NAME) or recipient_name
    customer_phone = attrs.get(NA_CUSTOMER_PHONE) or recipient_phone
    customer_email = attrs.get(NA_CUSTOMER_EMAIL) or order_email

    same = (
        _normalize_name(customer_name) == _normalize_name(recipient_name)
        and normalize_ua_phone(customer_phone) == normalize_ua_phone(recipient_phone)
    )

    return {
        "customer": _party(customer_name, customer_phone, customer_email),
        "recipient": _party(recipient_name, recipient_phone, recipient_email),
        "same": same,
    }


def _party(name: str, phone: str, email: str) -> Dict[str, str]:
    e164 = normalize_ua_phone(phone)
    return {
        "name": (name or "").strip(),
        "phone": (phone or "").strip(),
        "phone_e164": e164 or "",
        "phone_pretty": pretty_ua_phone(e164) if e164 else (phone or "").strip(),
        "email": (email or "").strip(),
    }


def get_customer_given_name(order: Dict[str, Any]) -> str:
    """Имя замовника для обращения «Вітаю, …».

    Chekly-заказы с отдельным замовником: первое слово `Customer Name`.
    Иначе — `shipping_address.first_name` (Shopify разбирает строку имени
    сам и на реальных заказах отдаёт именно имя, а не фамилию).
    """
    customer_name = note_attr(order, NA_CUSTOMER_NAME)
    if customer_name:
        return customer_name.split()[0]

    shipping = order.get("shipping_address") or {}
    first_name = (shipping.get("first_name") or "").strip()
    if first_name:
        return first_name

    recipient_name = note_attr(order, NA_RECIPIENT_NAME)
    if recipient_name:
        return recipient_name.split()[0]

    customer = order.get("customer") or {}
    return (customer.get("first_name") or "").strip()


def get_order_contact(order: Dict[str, Any]) -> Tuple[str, str, str]:
    """Кого бот считает клиентом заказа — **замовника**, то есть того, кто
    оформил и оплатил. Возвращает (first_name, last_name, phone_e164) для
    полей `customer_*` в БД: карточка бота, VCF, покупець у keyCRM.

    Если замовник и отримувач — один человек (обычный заказ), работает прежняя
    логика адресов: Shopify сам разбирает строку имени и на реальных заказах
    отдаёт имя и фамилию в правильном порядке.
    """
    attrs = note_attributes(order)
    customer_name = attrs.get(NA_CUSTOMER_NAME)

    if customer_name:
        # Chekly прислал отдельного замовника — значит получатель другой человек
        first_name, _, last_name = customer_name.partition(" ")
        phone = (
            normalize_ua_phone(attrs.get(NA_CUSTOMER_PHONE) or "")
            or normalize_ua_phone(order.get("phone") or "")
            or ""
        )
        return first_name.strip(), last_name.strip(), phone

    return _contact_from_addresses(order)


def _contact_from_addresses(order: Dict[str, Any]) -> Tuple[str, str, str]:
    """Прежняя логика: контакт из billing/shipping адресов заказа."""
    from app.services.address_utils import (
        get_contact_name,
        get_contact_phone_e164,
        get_delivery_and_contact_info,
    )

    _, contact_info = get_delivery_and_contact_info(order)
    first_name, last_name = get_contact_name(contact_info)

    customer = order.get("customer") or {}
    if not first_name and not last_name:
        first_name = (customer.get("first_name") or "").strip()
        last_name = (customer.get("last_name") or "").strip()

    phone_e164 = get_contact_phone_e164(contact_info)
    if not phone_e164:
        default_addr = customer.get("default_address") or {}
        for phone_source in (customer.get("phone"), order.get("phone"), default_addr.get("phone")):
            if phone_source and str(phone_source).strip():
                phone_e164 = normalize_ua_phone(str(phone_source).strip())
                if phone_e164:
                    break

    return first_name, last_name, phone_e164 or ""


def build_customer_line(order: Dict[str, Any], *, keep_phone_together: bool = False) -> str:
    """Строка «Замовник: ФІО, телефон» — выводится всегда.

    `keep_phone_together` склеивает телефон неразрывными пробелами, чтобы в PDF
    он не разрывался переносом строки посреди номера.
    """
    customer = get_parties(order)["customer"]
    phone = customer["phone_pretty"]
    if keep_phone_together and phone:
        phone = phone.replace(" ", " ")

    parts = [p for p in (customer["name"], phone) if p]
    return "Замовник: " + (", ".join(parts) or "—")


# ---------------------------------------------------------------------------
# Адрес доставки
# ---------------------------------------------------------------------------

def build_delivery_lines(order: Dict[str, Any]) -> List[str]:
    """Блок «Адреса доставки» — отримувач, отделение, город, индекс, страна,
    телефон отримувача, email.

    Для не-Chekly заказов используется старая логика billing/shipping.
    """
    if not is_chekly_order(order):
        from app.services.address_utils import (
            build_delivery_address_text,
            get_delivery_and_contact_info,
        )

        delivery_address, _ = get_delivery_and_contact_info(order)
        email = (order.get("email") or order.get("contact_email") or "").strip()
        text = build_delivery_address_text(delivery_address, email=email)
        return [line for line in text.split("\n") if line.strip()]

    attrs = note_attributes(order)
    shipping = order.get("shipping_address") or {}
    recipient = get_parties(order)["recipient"]

    lines: List[str] = []
    if recipient["name"]:
        lines.append(recipient["name"])

    for value in (
        attrs.get(NA_POST_OFFICE) or (shipping.get("address1") or "").strip(),
        attrs.get(NA_CITY) or (shipping.get("city") or "").strip(),
        attrs.get(NA_ZIP) or (shipping.get("zip") or "").strip(),
        attrs.get(NA_COUNTRY) or (shipping.get("country") or "").strip(),
    ):
        if value:
            lines.append(value)

    if recipient["phone_pretty"]:
        lines.append(recipient["phone_pretty"])

    lines.append(recipient["email"] or "—")
    return lines


def build_delivery_short(order: Dict[str, Any]) -> str:
    """Короткий адрес одной строкой для карточки в Telegram."""
    attrs = note_attributes(order)
    shipping = order.get("shipping_address") or {}

    city = attrs.get(NA_CITY) or (shipping.get("city") or "").strip()
    point = attrs.get(NA_POST_OFFICE) or (shipping.get("address1") or "").strip()

    return ", ".join(p for p in (city, point) if p)
