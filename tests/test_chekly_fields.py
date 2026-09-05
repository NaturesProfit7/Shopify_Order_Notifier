# tests/test_chekly_fields.py
"""Извлечение полей заказов Chekly: оплата, замовник/отримувач, адрес."""
import pytest

from app.services import order_fields as fields
from tests.fixtures.chekly_orders import order


# --- оплата ----------------------------------------------------------------

def test_partial_payment_amounts_from_total_outstanding():
    info = fields.get_payment_info(order("PARTIAL_SAME_PERSON"))

    assert info["status"] == "partially_paid"
    assert info["label"] == "Частково сплачено"
    assert info["is_partial"] is True
    assert info["total"] == 550.0
    assert info["paid"] == 200.0
    assert info["outstanding"] == 350.0


def test_full_payment():
    info = fields.get_payment_info(order("PAID_DIFFERENT_PEOPLE"))

    assert info["label"] == "Сплачено"
    assert info["is_partial"] is False
    assert info["paid"] == 1.0


def test_partial_payment_falls_back_to_note_attribute():
    """Если Shopify не прислал total_outstanding — берём сумму из note_attributes."""
    raw = order("PARTIAL_SAME_PERSON")
    raw.pop("total_outstanding")

    info = fields.get_payment_info(raw)

    assert info["paid"] == 200.0
    assert info["outstanding"] == 350.0


def test_payment_block_partial():
    assert fields.build_payment_block(order("PARTIAL_SAME_PERSON")) == [
        ("Статус оплати:", "Частково сплачено"),
        ("Передоплата:", "200.00 UAH"),
        ("Залишок:", "350.00 UAH"),
    ]


def test_payment_block_full():
    assert fields.build_payment_block(order("PAID_DIFFERENT_PEOPLE")) == [
        ("Статус оплати:", "Сплачено"),
    ]


def test_unknown_financial_status_hides_the_block():
    raw = order("PAID_DIFFERENT_PEOPLE")
    raw["financial_status"] = "something_new"

    assert fields.build_payment_block(raw) == []


@pytest.mark.parametrize("status,label", [
    ("refunded", "Повернено"),
    ("partially_refunded", "Частково повернено"),
    ("voided", "Скасовано"),
    ("pending", "Очікує оплату"),
])
def test_other_statuses_are_translated(status, label):
    raw = order("PAID_DIFFERENT_PEOPLE")
    raw["financial_status"] = status

    assert fields.get_payment_info(raw)["label"] == label


# --- замовник и отримувач --------------------------------------------------

def test_same_person_when_customer_attributes_are_absent():
    parties = fields.get_parties(order("PARTIAL_SAME_PERSON"))

    assert parties["same"] is True
    assert parties["customer"]["name"] == parties["recipient"]["name"] == "Тестова Олена"
    assert parties["customer"]["phone_e164"] == "+380631112233"


def test_different_people_are_taken_from_note_attributes():
    parties = fields.get_parties(order("PAID_DIFFERENT_PEOPLE"))

    assert parties["same"] is False
    assert parties["customer"]["name"] == "Замовник Тестовий"
    assert parties["customer"]["phone_e164"] == "+380931112255"
    assert parties["recipient"]["name"] == "Тестовий Отримувач"
    assert parties["recipient"]["phone_e164"] == "+380931112244"


def test_customer_block_has_name_phone_and_email():
    """Замовник — отдельным блоком: заголовок, ФИО, телефон, почта."""
    assert fields.build_customer_block(order("PAID_DIFFERENT_PEOPLE")) == [
        ("Замовник:", ""),
        ("", "Замовник Тестовий"),
        ("", "+380 93 111 22 55"),
        ("", "buyer@example.com"),
    ]


def test_customer_block_for_a_single_person():
    assert fields.build_customer_block(order("PARTIAL_SAME_PERSON")) == [
        ("Замовник:", ""),
        ("", "Тестова Олена"),
        ("", "+380 63 111 22 33"),
        ("", "test.customer@example.com"),
    ]


def test_given_name_for_greeting():
    # замовник отдельно — берём первое слово Customer Name
    assert fields.get_customer_given_name(order("PAID_DIFFERENT_PEOPLE")) == "Замовник"
    # один человек — берём разбор имени от Shopify
    assert fields.get_customer_given_name(order("PARTIAL_SAME_PERSON")) == "Олена"


# --- адрес и доставка ------------------------------------------------------

def test_delivery_block_uses_note_attributes():
    """Отримувач, телефон, відділення і одной строкой місто/індекс/країна."""
    assert fields.build_delivery_block(order("PAID_DIFFERENT_PEOPLE")) == [
        ("Доставка:", "Нова Пошта"),
        ("Адреса доставки:", ""),
        ("", "Тестовий Отримувач"),
        ("", "+380 93 111 22 44"),
        ("", "Відділення №1: вул. Пирогівський шлях, 135"),
        ("", "м. Київ, Київська, 03026, Ukraine"),
    ]


def test_delivery_block_falls_back_to_address_for_legacy_orders():
    raw = order("LEGACY_ORDER")

    assert fields.is_chekly_order(raw) is False
    assert fields.build_delivery_block(raw) == [
        ("Доставка:", "Нова Пошта"),
        ("Адреса доставки:", ""),
        ("", "Дарія Легасі"),
        ("", "+380 95 111 22 33"),
        ("", "Відділення №5"),
        ("", "Одеса, 65125, Ukraine"),
    ]


def test_header_blocks_order_and_separation():
    """Порядок блоков шапки: дата → оплата → замовник → доставка."""
    blocks = fields.build_header_blocks(order("PARTIAL_SAME_PERSON"), "05.09.2026 19:52")

    assert [block[0][0] for block in blocks] == [
        "Дата:", "Статус оплати:", "Замовник:", "Доставка:",
    ]


def test_header_text_puts_a_blank_line_between_blocks():
    blocks = fields.build_header_blocks(order("PARTIAL_SAME_PERSON"), "05.09.2026 19:52")

    assert fields.render_header_text(blocks) == [
        "Дата: 05.09.2026 19:52",
        "",
        "Статус оплати: Частково сплачено",
        "Передоплата: 200.00 UAH",
        "Залишок: 350.00 UAH",
        "",
        "Замовник:",
        "Тестова Олена",
        "+380 63 111 22 33",
        "test.customer@example.com",
        "",
        "Доставка: Нова Пошта",
        "Адреса доставки:",
        "Тестова Олена",
        "+380 63 111 22 33",
        "Відділення №18 (до 30 кг): вул. Фонтанська дорога, 16/8",
        "м. Одеса, Одеська, 65049, Ukraine",
    ]


def test_delivery_short_for_telegram_card():
    assert fields.build_delivery_short(order("PARTIAL_SAME_PERSON")) == (
        "м. Одеса, Одеська, Відділення №18 (до 30 кг): вул. Фонтанська дорога, 16/8"
    )


def test_checkout_id():
    assert fields.get_checkout_id(order("PAID_DIFFERENT_PEOPLE")) == (
        "e092a38a-3327-4ec2-a24d-0bacca9c97d9"
    )
    assert fields.get_checkout_id(order("LEGACY_ORDER")) is None


def test_delivery_service_is_always_nova_poshta():
    """Chekly не заполняет shipping_lines — способ доставки у нас один."""
    assert fields.DELIVERY_SERVICE == "Нова Пошта"
    assert order("PAID_DIFFERENT_PEOPLE")["shipping_lines"] == []


# --- кого бот считает клиентом заказа --------------------------------------

def test_order_contact_is_the_customer_not_the_recipient():
    """Заказчик и получатель разные — в БД должен попасть заказчик."""
    assert fields.get_order_contact(order("PAID_DIFFERENT_PEOPLE")) == (
        "Замовник", "Тестовий", "+380931112255",
    )


def test_order_contact_unchanged_when_one_person():
    """Обычный заказ — прежнее поведение, разбор имени от Shopify."""
    assert fields.get_order_contact(order("PARTIAL_SAME_PERSON")) == (
        "Олена", "Тестова", "+380631112233",
    )


def test_order_contact_for_legacy_orders():
    assert fields.get_order_contact(order("LEGACY_ORDER")) == (
        "Дарія", "Легасі", "+380951112233",
    )


def test_order_contact_falls_back_to_order_phone():
    """Chekly прислал замовника без телефона — берём телефон заказа."""
    raw = order("PAID_DIFFERENT_PEOPLE")
    raw["note_attributes"] = [
        na for na in raw["note_attributes"] if na["name"] != "Customer Phone"
    ]

    assert fields.get_order_contact(raw) == ("Замовник", "Тестовий", "+380931112255")
