# tests/test_bot_contact_block.py
"""Верх карточки заказа: замовник и, если он не получатель, отдельно отримувач."""
from types import SimpleNamespace

from app.bot.services.message_builder import build_contact_block, build_recipient_line
from app.services.order_fields import get_order_contact
from tests.fixtures.chekly_orders import order


def _order(fixture):
    """Заказ так, как он лежал бы в БД после обработки вебхука."""
    raw = order(fixture)
    first_name, last_name, phone = get_order_contact(raw)
    return SimpleNamespace(
        customer_first_name=first_name,
        customer_last_name=last_name,
        customer_phone_e164=phone,
        raw_json=raw,
    )


def test_contact_block_shows_both_people_when_they_differ():
    assert build_contact_block(_order("PAID_DIFFERENT_PEOPLE")) == (
        "👤 <b>Замовник:</b> Замовник Тестовий\n"
        "📱 +380931112255\n"
        "📦 <b>Отримувач:</b> Тестовий Отримувач • +380931112244"
    )


def test_contact_block_unchanged_for_a_single_person():
    """Обычный заказ — без подписи «Замовник» и без строки отримувача."""
    assert build_contact_block(_order("PARTIAL_SAME_PERSON")) == (
        "👤 Олена Тестова\n📱 +380631112233"
    )


def test_contact_block_for_legacy_orders():
    assert build_contact_block(_order("LEGACY_ORDER")) == (
        "👤 Дарія Легасі\n📱 +380951112233"
    )


def test_recipient_line_only_for_split_orders():
    assert build_recipient_line(order("PAID_DIFFERENT_PEOPLE")) is not None
    assert build_recipient_line(order("PARTIAL_SAME_PERSON")) is None
    assert build_recipient_line(order("LEGACY_ORDER")) is None
    assert build_recipient_line(None) is None
