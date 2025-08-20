import asyncio
from unittest.mock import Mock, patch

from app.bot.routers.commands import on_menu, main_menu_buttons


def test_menu_command_sends_two_buttons():
    with patch("app.bot.routers.commands.send_text_with_buttons") as send_mock:
        asyncio.run(on_menu(Mock()))
        send_mock.assert_called_once()
        args, kwargs = send_mock.call_args
        assert args[0] == "Главное меню"
        buttons = args[1]
        assert buttons == main_menu_buttons()
        assert len(buttons) == 2
        assert all(len(row) == 1 for row in buttons)
