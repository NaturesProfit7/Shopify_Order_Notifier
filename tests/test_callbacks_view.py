import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, Mock
import os


class DummySession:
    def __init__(self, order):
        self._order = order
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        pass
    def get(self, model, _id):
        return self._order


def test_on_order_view_sends_detailed_message():
    order = SimpleNamespace(id=123)
    cb = Mock()
    cb.data = "order:123:view"
    cb.answer = AsyncMock()

    with patch.dict(os.environ, {"DATABASE_URL": "sqlite://"}):
        from app.bot.routers.callbacks import on_order_view_click

        with patch("app.bot.routers.callbacks.get_session", return_value=DummySession(order)), \
             patch("app.bot.routers.callbacks.build_order_message", return_value="DETAILS") as build_mock, \
             patch("app.bot.routers.callbacks.order_card_buttons", return_value=[[{"text": "PDF"}]]) as buttons_mock, \
             patch("app.bot.routers.callbacks.send_text_with_buttons", new_callable=AsyncMock) as send_mock:
            asyncio.run(on_order_view_click(cb))

            build_mock.assert_called_once_with(order, detailed=True)
            buttons_mock.assert_called_once_with(order.id)
            send_mock.assert_awaited_once_with("DETAILS", [[{"text": "PDF"}]])
            cb.answer.assert_awaited()
