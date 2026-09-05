# tests/test_bot_contact_block.py
"""Верх карточки заказа и комментарий покупателя в сообщениях бота."""
from types import SimpleNamespace

from app.bot.services.message_builder import build_buyer_comment_line, build_contact_block
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


def test_contact_block_shows_the_customer():
    """В карточке — замовник; отримувача здесь не показываем."""
    assert build_contact_block(_order("PAID_DIFFERENT_PEOPLE")) == (
        "👤 Тестовий Замовник\n📱 +380931112255"
    )
    assert "Отримувач" not in build_contact_block(_order("PAID_DIFFERENT_PEOPLE"))


def test_contact_block_for_a_single_person():
    assert build_contact_block(_order("PARTIAL_SAME_PERSON")) == (
        "👤 Олена Тестова\n📱 +380631112233"
    )


def test_contact_block_for_legacy_orders():
    assert build_contact_block(_order("LEGACY_ORDER")) == (
        "👤 Дарія Легасі\n📱 +380951112233"
    )


# --- комментарий покупателя ------------------------------------------------

def test_buyer_comment_line():
    assert build_buyer_comment_line(order("PAID_DIFFERENT_PEOPLE")) == (
        "📝 <b>Коментар покупця:</b> Тестовий коментар до великого замовлення"
    )


def test_no_line_when_buyer_left_no_comment():
    assert build_buyer_comment_line(order("PARTIAL_SAME_PERSON")) is None
    assert build_buyer_comment_line(None) is None


def test_buyer_comment_falls_back_to_shopify_note():
    assert build_buyer_comment_line({"note": "з нотаток Shopify"}) == (
        "📝 <b>Коментар покупця:</b> з нотаток Shopify"
    )


def test_buyer_comment_is_html_escaped():
    """Текст пишет покупатель, а сообщение уходит с parse_mode=HTML."""
    line = build_buyer_comment_line({"note": "<b>шрифт</b> & <script>"})

    assert "&lt;b&gt;шрифт&lt;/b&gt; &amp; &lt;script&gt;" in line


# --- рядок про адресу в повідомленні після створення замовлення -------------

def test_shipping_note_for_a_bound_warehouse():
    from app.bot.routers.management import _format_shipping_note

    assert _format_shipping_note({"shipping_kind": "warehouse", "shipping_degraded": False}) == (
        "\n\n📍 Адресу доставки перенесено, відділення прив'язано"
    )


def test_shipping_note_warns_when_binding_failed():
    from app.bot.routers.management import _format_shipping_note

    note = _format_shipping_note({"shipping_kind": "address", "shipping_degraded": True})

    assert note.startswith("\n\n⚠️")
    assert "без прив'язки" in note


def test_no_shipping_note_when_order_has_no_address():
    from app.bot.routers.management import _format_shipping_note

    assert _format_shipping_note({"shipping_kind": "empty", "shipping_degraded": False}) == ""
