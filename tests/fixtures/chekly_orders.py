# tests/fixtures/chekly_orders.py
"""Заказы Shopify, оформленные через платёжку Chekly.

Структура повторяет реальные заказы #4580 и #4582 (включая пустые
`shipping_lines`, `billing_address: null` и перевёрнутые first/last name
в `shipping_address`), персональные данные заменены.

* PARTIAL_SAME_PERSON — частичная оплата, замовник = отримувач
* PAID_DIFFERENT_PEOPLE — полная оплата, замовник ≠ отримувач
"""
from __future__ import annotations

import copy
from typing import Any, Dict


def _note(name: str, value: str) -> Dict[str, str]:
    return {"name": name, "value": value}


# Частичная оплата (200 из 550), замовник и отримувач — один человек:
# атрибутов Customer Name / Customer Phone нет вообще.
PARTIAL_SAME_PERSON: Dict[str, Any] = {
    "id": 7441887789359,
    "order_number": "4580",
    "created_at": "2026-09-05T19:52:11+03:00",
    "currency": "UAH",
    "email": "test.customer@example.com",
    "phone": "+380631112233",
    "financial_status": "partially_paid",
    "total_price": "550.00",
    "total_outstanding": "350.00",
    "checkout_token": "6daad0a8c24c269d7aa76dc631bafbf4",
    "gateway": None,
    "payment_gateway_names": ["manual"],
    "shipping_lines": [],
    "billing_address": None,
    "shipping_address": {
        "zip": "65049",
        "city": "м. Одеса, Одеська",
        "name": "Тестова Олена",
        "phone": "+380631112233",
        "company": None,
        "country": "Ukraine",
        "address1": "Відділення №18 (до 30 кг): вул. Фонтанська дорога, 16/8",
        "address2": None,
        "province": None,
        "last_name": "Тестова",
        "first_name": "Олена",
        "country_code": "UA",
        "province_code": None,
    },
    "customer": {"first_name": "Олена", "last_name": "Тестова"},
    "note_attributes": [
        _note("Recipient Name", "Тестова Олена"),
        _note("Recipient Phone", "+380631112233"),
        _note("Recipient Email", "test.customer@example.com"),
        _note("Delivery Method", "Нова пошта"),
        _note("City", "м. Одеса, Одеська"),
        _note("Post Office", "Відділення №18 (до 30 кг): вул. Фонтанська дорога, 16/8"),
        _note("_zip-code", "65049"),
        _note("Payment", "Накладений платіж"),
        _note("Shipping", "За тарифами перевізника"),
        _note("_provider", "Нова пошта"),
        _note("_country", "Ukraine"),
        _note("_delivery_type", "branch"),
        _note("_delivery_city", "м. Одеса, Одеська обл."),
        _note("_delivery_warehouse", "Відділення №18 (до 30 кг): вул. Фонтанська дорога, 16/8"),
        _note("_delivery_warehouse_address", "Одеса, Фонтанська дорога, 16/8"),
        _note("_delivery_warehouse_Number", "18"),
        _note("_delivery_warehouse_Ref", "1ec09d48-e1c2-11e3-8c4a-0050568002cf"),
        _note("_checkout_lang", "ua"),
        _note("Currency rate", "1"),
        _note("Cash on delivery", "true"),
        _note("Partial payment value - Monobank", "200 UAH"),
        _note("Checkout id", "9494cb38-0f81-40b1-8dbc-bf1098d98826"),
    ],
    "line_items": [
        {
            "title": "Адресник квітка",
            "quantity": 1,
            "price": "550.00",
            "variant_title": None,
            "properties": [
                {"name": "Колір медальки", "value": "золото"},
                {"name": "Дизайн медальки", "value": "лапка"},
                {"name": "Колір шнурочка", "value": "6. Коричневий"},
                {"name": "Кличка улюбленця", "value": "МІЯ"},
                {"name": "Номер телефону", "value": "+380631112233"},
                {"name": "Додати другий номер або фразу (+50 грн)", "value": "Ні"},
                {"name": "Обхват шиї (або порода і вік улюбленця)", "value": "26, той пудель, 9 місяців"},
            ],
        }
    ],
}

# Полная оплата, замовник и отримувач — разные люди.
PAID_DIFFERENT_PEOPLE: Dict[str, Any] = {
    "id": 7441887789999,
    "order_number": "4582",
    "created_at": "2026-09-05T22:40:03+03:00",
    "currency": "UAH",
    "email": "buyer@example.com",
    "phone": "+380931112255",
    "financial_status": "paid",
    "total_price": "1.00",
    "total_outstanding": "0.00",
    "checkout_token": "f92bd32f771b456a150bbf6cd77e56de",
    "gateway": None,
    "payment_gateway_names": ["manual"],
    "shipping_lines": [],
    "billing_address": None,
    "shipping_address": {
        "zip": "03026",
        "city": "м. Київ, Київська",
        "name": "Отримувач Тестовий",
        "phone": "+380931112244",
        "company": None,
        "country": "Ukraine",
        "address1": "Відділення №1: вул. Пирогівський шлях, 135",
        "address2": None,
        "province": None,
        # Shopify разбирает строку имени в обратном порядке — так в проде
        "last_name": "Тестовий",
        "first_name": "Отримувач",
        "country_code": "UA",
        "province_code": None,
    },
    "customer": {"first_name": "Отримувач", "last_name": "Тестовий"},
    "note_attributes": [
        _note("Recipient Name", "Тестовий Отримувач"),
        _note("Checkout id", "e092a38a-3327-4ec2-a24d-0bacca9c97d9"),
        _note("Recipient Phone", "+380931112244"),
        _note("Customer Phone", "+380931112255"),
        _note("Customer Name", "Замовник Тестовий"),
        _note("Customer Email", "buyer@example.com"),
        _note("Delivery Method", "Нова пошта"),
        _note("City", "м. Київ, Київська"),
        _note("Post Office", "Відділення №1: вул. Пирогівський шлях, 135"),
        _note("_zip-code", "03026"),
        _note("Payment", "Monobank"),
        _note("Comment", "Тестовий коментар до великого замовлення"),
        _note("Shipping", "За тарифами перевізника"),
        _note("_provider", "Нова пошта"),
        _note("_country", "Ukraine"),
        _note("_delivery_type", "branch"),
        _note("_delivery_warehouse", "Відділення №1: вул. Пирогівський шлях, 135"),
        _note("_delivery_warehouse_address", "Київ, Пирогівський шлях, 135"),
        _note("_delivery_warehouse_Number", "1"),
        _note("_delivery_warehouse_Ref", "1ec09d88-e1c2-11e3-8c4a-0050568002cf"),
        _note("_checkout_lang", "ua"),
        _note("Currency rate", "1"),
    ],
    "line_items": [
        {
            "title": "тест",
            "quantity": 1,
            "price": "1.00",
            "variant_title": None,
            "properties": [],
        }
    ],
}

# Старый заказ (до Chekly): shipping_lines заполнены, note_attributes нет
LEGACY_ORDER: Dict[str, Any] = {
    "id": 7441000000001,
    "order_number": "3475",
    "created_at": "2026-05-23T13:49:00+03:00",
    "currency": "UAH",
    "email": "legacy@example.com",
    "financial_status": "paid",
    "total_price": "550.00",
    "shipping_lines": [{"title": "Нова Пошта"}],
    "billing_address": None,
    "shipping_address": {
        "zip": "65125",
        "city": "Одеса",
        "phone": "+380951112233",
        "country": "Ukraine",
        "address1": "Відділення №5",
        "last_name": "Легасі",
        "first_name": "Дарія",
    },
    "customer": {"first_name": "Дарія", "last_name": "Легасі"},
    "note_attributes": [],
    "line_items": [
        {"title": "Адресник ПІДВІСКА", "quantity": 1, "price": "550.00", "variant_title": "20 мм", "properties": []}
    ],
}


def order(name: str) -> Dict[str, Any]:
    """Глубокая копия фикстуры, чтобы тесты не мутировали общий объект."""
    return copy.deepcopy(globals()[name])
