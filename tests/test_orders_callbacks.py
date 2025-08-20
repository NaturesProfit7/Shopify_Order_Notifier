import os
import sys
import types
import asyncio
from unittest.mock import patch, MagicMock


# Ensure environment configuration for import
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SHOPIFY_STORE_DOMAIN", "example.myshopify.com")
os.environ.setdefault("SHOPIFY_ADMIN_ACCESS_TOKEN", "dummy")

# Provide stub for bot main to avoid heavy deps
fake_bot_main = types.ModuleType("app.bot.main")
fake_bot_main.start_bot = lambda: None
fake_bot_main.stop_bot = lambda: None
fake_bot_main.get_bot = lambda: None
sys.modules.setdefault("app.bot.main", fake_bot_main)

from app.main import telegram_webhook
from app.services.menu_ui import orders_list_buttons, order_card_buttons


class DummyRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def test_orders_list_pending_calls_send_with_filtered_orders():
    data = {"callback_query": {"id": "cb1", "data": "orders:list:pending:offset=0"}}
    fake_buttons = [[{"text": "o1", "callback_data": "order:1:view"}]]
    with patch("app.main.get_session") as get_session_mock, \
         patch("app.main.send_text_with_buttons") as send_mock, \
         patch("app.main.orders_list_buttons", return_value=fake_buttons) as list_mock, \
         patch("app.main.answer_callback_query") as answer_mock:
        asyncio.run(telegram_webhook(DummyRequest(data)))
        send_mock.assert_called_once_with("Список замовлень (pending) 1/1", fake_buttons)
        list_mock.assert_called_once_with(
            "pending", 0, page_size=10, has_prev=False, has_next=False
        )
        answer_mock.assert_called_once_with("cb1")
        get_session_mock.assert_not_called()


def test_orders_list_all_shows_all_orders():
    data = {"callback_query": {"id": "cb2", "data": "orders:list:all:offset=0"}}
    fake_buttons = [[{"text": "o2", "callback_data": "order:2:view"}]]
    with patch("app.main.get_session") as get_session_mock, \
         patch("app.main.send_text_with_buttons") as send_mock, \
         patch("app.main.orders_list_buttons", return_value=fake_buttons) as list_mock, \
         patch("app.main.answer_callback_query") as answer_mock:
        asyncio.run(telegram_webhook(DummyRequest(data)))
        send_mock.assert_called_once_with("Список замовлень (all) 1/1", fake_buttons)
        list_mock.assert_called_once_with(
            "all", 0, page_size=10, has_prev=False, has_next=False
        )
        answer_mock.assert_called_once_with("cb2")
        get_session_mock.assert_not_called()


def test_order_view_sends_card():
    data = {"callback_query": {"id": "cb3", "data": "order:5:view"}}
    fake_buttons = [[{"text": "PDF", "callback_data": "order:5:resend:pdf"}]]
    with patch("app.main.get_session") as get_session_mock, \
         patch("app.main.send_text_with_buttons") as send_mock, \
         patch("app.main.order_card_buttons", return_value=fake_buttons) as card_mock, \
         patch("app.main.answer_callback_query") as answer_mock:
        asyncio.run(telegram_webhook(DummyRequest(data)))
        send_mock.assert_called_once_with("Картка замовлення #5", fake_buttons)
        card_mock.assert_called_once_with(5)
        answer_mock.assert_called_once_with("cb3")
        get_session_mock.assert_not_called()


def test_orders_list_buttons_structure():
    buttons = orders_list_buttons(
        "pending", 10, page_size=10, has_prev=True, has_next=True
    )
    assert buttons == [
        [
            {"text": "⬅️", "callback_data": "orders:list:pending:offset=0"},
            {"text": "➡️", "callback_data": "orders:list:pending:offset=20"},
        ]
    ]
    last_page = orders_list_buttons(
        "pending", 10, page_size=10, has_prev=True, has_next=False
    )
    assert last_page == [
        [{"text": "⬅️", "callback_data": "orders:list:pending:offset=0"}]
    ]
    first_page = orders_list_buttons(
        "all", 0, page_size=5, has_prev=False, has_next=True
    )
    assert first_page == [
        [{"text": "➡️", "callback_data": "orders:list:all:offset=5"}]
    ]


def test_order_card_buttons_structure():
    buttons = order_card_buttons(7)
    assert buttons[0] == [
        {"text": "PDF", "callback_data": "order:7:resend:pdf"},
        {"text": "VCF", "callback_data": "order:7:resend:vcf"},
    ]
    assert buttons[1] == [{"text": "Назад", "callback_data": "orders:list:pending:offset=0"}]
