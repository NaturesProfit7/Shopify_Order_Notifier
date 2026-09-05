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
NA_COMMENT = "Comment"
NA_POSTOMAT = "Postomat"
NA_DELIVERY_TYPE = "_delivery_type"
NA_WAREHOUSE = "_delivery_warehouse"
NA_WAREHOUSE_REF = "_delivery_warehouse_Ref"
NA_WAREHOUSE_ADDRESS = "_delivery_warehouse_address"
NA_COURIER_ADDRESS = "_delivery_courier_address"
NA_STREET = "Street"
NA_HOUSE = "House"

# Курьерская доставка: склада нет, есть улица с домом.
# У отделения и почтомата `_delivery_type` одинаковый — «branch».
COURIER_DELIVERY_TYPES = {"courier", "address", "door"}

_PARTIAL_PAYMENT_PREFIX = "partial payment value"

# Строка шапки документа: (заголовок, значение).
# Заголовок печатается жирным, значение — обычным шрифтом; любая часть
# может быть пустой: («Замовник:», "") — заголовок блока, ("", "+380…") — данные.
HeaderLine = Tuple[str, str]


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


def get_buyer_comment(order: Dict[str, Any]) -> str:
    """Комментарий покупателя из оформления заказа.

    Chekly кладёт его в note_attribute `Comment`; в админке Shopify это же
    поле видно как «Примечания» (`order.note`).
    """
    return note_attr(order, NA_COMMENT) or (order.get("note") or "").strip()


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


def build_payment_block(order: Dict[str, Any]) -> List[HeaderLine]:
    """Блок оплаты:

        Статус оплати: Частково сплачено
        Передоплата: 200.00 UAH
        Залишок: 350.00 UAH
    """
    info = get_payment_info(order)
    if not info["label"]:
        return []

    lines: List[HeaderLine] = [("Статус оплати:", info["label"])]
    if info["is_partial"]:
        if info["paid"] is not None:
            lines.append(("Передоплата:", format_money(info["paid"], info["currency"])))
        if info["outstanding"] is not None:
            lines.append(("Залишок:", format_money(info["outstanding"], info["currency"])))
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


def split_chekly_name(full_name: str) -> Tuple[str, str]:
    """Разбирает имя из note_attributes Chekly на (имя, фамилию).

    Chekly отдаёт имя одной строкой в порядке «Прізвище Ім'я»: это видно из
    того, как ту же строку разбирает Shopify — для `Recipient Name` =
    «Ковальова Анна» в shipping_address приходит first_name «Анна»,
    last_name «Ковальова». То есть имя — последнее слово строки.
    """
    parts = (full_name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def get_customer_given_name(order: Dict[str, Any]) -> str:
    """Имя замовника для обращения «Вітаю, …»."""
    customer_name = note_attr(order, NA_CUSTOMER_NAME)
    if customer_name:
        return split_chekly_name(customer_name)[0]

    # Замовник = отримувач: Shopify уже разобрал строку имени за нас
    shipping = order.get("shipping_address") or {}
    first_name = (shipping.get("first_name") or "").strip()
    if first_name:
        return first_name

    recipient_name = note_attr(order, NA_RECIPIENT_NAME)
    if recipient_name:
        return split_chekly_name(recipient_name)[0]

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
        first_name, last_name = split_chekly_name(customer_name)
        phone = (
            normalize_ua_phone(attrs.get(NA_CUSTOMER_PHONE) or "")
            or normalize_ua_phone(order.get("phone") or "")
            or ""
        )
        return first_name, last_name, phone

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


def build_customer_block(order: Dict[str, Any]) -> List[HeaderLine]:
    """Блок замовника — выводится всегда:

        Замовник:
        Ковальова Анна
        +380 63 317 44 76
        anakovalova075@gmail.com
    """
    customer = get_parties(order)["customer"]

    lines: List[HeaderLine] = [("Замовник:", "")]
    for value in (customer["name"], customer["phone_pretty"], customer["email"]):
        if value:
            lines.append(("", value))

    if len(lines) == 1:
        lines.append(("", "—"))
    return lines


# ---------------------------------------------------------------------------
# Адрес доставки
# ---------------------------------------------------------------------------

def build_delivery_block(order: Dict[str, Any]) -> List[HeaderLine]:
    """Блок доставки — отримувач с адресом идут сразу под способом доставки:

        Доставка: Нова Пошта
        Ковальова Анна
        +380 63 317 44 76
        Відділення №18 (до 30 кг): вул. Фонтанська дорога, 16/8
        м. Одеса, Одеська, 65049, Ukraine
    """
    if is_chekly_order(order):
        attrs = note_attributes(order)
        shipping = order.get("shipping_address") or {}
        recipient = get_parties(order)["recipient"]

        delivery = get_delivery_details(order)
        name = recipient["name"]
        phone = recipient["phone_pretty"]
        # відділення, поштомат або адреса кур'єрської доставки
        point = delivery["pickup_point"] or delivery["courier_address"]
        extra = ""
        location = [
            attrs.get(NA_CITY) or (shipping.get("city") or "").strip(),
            delivery["zip"],
            delivery["country"],
        ]
    else:
        # Заказы до Chekly: адрес выбирается прежней логикой billing/shipping
        from app.services.address_utils import get_delivery_and_contact_info

        address, _ = get_delivery_and_contact_info(order)
        name = _shipping_full_name(address)
        phone_e164 = normalize_ua_phone((address.get("phone") or "").strip())
        phone = pretty_ua_phone(phone_e164) if phone_e164 else (address.get("phone") or "").strip()
        point = (address.get("address1") or "").strip()
        extra = (address.get("address2") or "").strip()
        location = [
            (address.get("city") or "").strip(),
            (address.get("zip") or "").strip(),
            (address.get("country") or "").strip(),
        ]

    lines: List[HeaderLine] = [("Доставка:", DELIVERY_SERVICE)]
    for value in (name, phone, point, extra, ", ".join(p for p in location if p)):
        if value:
            lines.append(("", value))
    return lines


def build_header_blocks(order: Dict[str, Any], created: str) -> List[List[HeaderLine]]:
    """Вся шапка документа блоками — между блоками пустая строка.

    Один и тот же порядок и в PDF, и в комментарии менеджера в keyCRM.
    """
    blocks = [[("Дата:", created)]]

    payment = build_payment_block(order)
    if payment:
        blocks.append(payment)

    blocks.append(build_customer_block(order))
    blocks.append(build_delivery_block(order))
    return blocks


def render_header_text(blocks: List[List[HeaderLine]]) -> List[str]:
    """Блоки шапки в обычный текст (для keyCRM, где нет жирного шрифта)."""
    lines: List[str] = []
    for index, block in enumerate(blocks):
        if index:
            lines.append("")
        for label, value in block:
            lines.append(" ".join(part for part in (label, value) if part))
    return lines


def get_delivery_details(order: Dict[str, Any]) -> Dict[str, str]:
    """Разобранный адрес доставки — для блока `shipping` в keyCRM.

    Chekly отдаёт не только текст, но и справочные идентификаторы Нової Пошти:
    `_delivery_warehouse_Ref` — UUID отделения, по нему keyCRM привязывает склад
    и может оформить ТТН без ручного выбора.

    Город и область приходят одной строкой («м. Київ, Київська») — режем по
    последней запятой.
    """
    attrs = note_attributes(order)
    shipping = order.get("shipping_address") or {}

    # «м. Київ, Київська» → місто + область
    # «с. Абазівка, Полтавський, Полтавська» → місто + район + область
    parts = [p.strip() for p in (attrs.get(NA_CITY) or (shipping.get("city") or "")).split(",") if p.strip()]
    city = parts[0] if parts else ""
    region = parts[-1] if len(parts) > 1 else ""

    delivery_type = attrs.get(NA_DELIVERY_TYPE, "")
    is_courier = delivery_type in COURIER_DELIVERY_TYPES
    warehouse_ref = attrs.get(NA_WAREHOUSE_REF, "")

    return {
        "city": city,
        "region": region or (shipping.get("province") or "").strip(),
        "zip": attrs.get(NA_ZIP) or (shipping.get("zip") or "").strip(),
        "country": attrs.get(NA_COUNTRY) or (shipping.get("country") or "").strip(),
        "pickup_point": "" if is_courier else _pickup_point(attrs, shipping),
        "courier_address": _courier_address(attrs) if is_courier else "",
        "warehouse_address": attrs.get(NA_WAREHOUSE_ADDRESS, ""),
        "delivery_type": delivery_type,
        "is_courier": is_courier,
        # у кур'єрської доставки складу немає, чужий ref зламав би прив'язку
        "warehouse_ref": "" if is_courier else warehouse_ref,
    }


def _pickup_point(attrs: Dict[str, str], shipping: Dict[str, Any]) -> str:
    """Отделение или почтомат: Chekly кладёт их в разные атрибуты."""
    return (
        attrs.get(NA_POST_OFFICE)
        or attrs.get(NA_POSTOMAT)
        or attrs.get(NA_WAREHOUSE)
        or (shipping.get("address1") or "").strip()
    )


def _courier_address(attrs: Dict[str, str]) -> str:
    """Адрес курьерской доставки: улица, дом, квартира."""
    ready = attrs.get(NA_COURIER_ADDRESS)
    if ready:
        return ready

    parts = [attrs.get(NA_STREET, ""), attrs.get(NA_HOUSE, "")]
    return ", ".join(p.strip(" ,") for p in parts if p.strip(" ,"))


def build_delivery_short(order: Dict[str, Any]) -> str:
    """Короткий адрес одной строкой для карточки в Telegram."""
    attrs = note_attributes(order)
    shipping = order.get("shipping_address") or {}
    delivery = get_delivery_details(order)

    city = attrs.get(NA_CITY) or (shipping.get("city") or "").strip()
    point = delivery["pickup_point"] or delivery["courier_address"]

    return ", ".join(p for p in (city, point) if p)
