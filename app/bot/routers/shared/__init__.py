# app/bot/routers/shared/__init__.py
"""Общие компоненты для роутеров бота"""

from .utils import (
    debug_print,
    check_permission,
    format_phone_compact,
    track_navigation_message,
    track_order_file_message,
    cleanup_order_files,
    cleanup_all_navigation,
    update_navigation_message,
    safe_edit_message,
    safe_delete_message
)

from .state import (
    get_navigation_message_id,
    set_navigation_message_id,
    remove_navigation_message_id,
    add_order_file_message,
    get_order_file_messages,
    clear_order_file_messages,
    clear_all_user_files
)

from .keyboards import (
    main_menu_keyboard,
    stats_keyboard,
    back_to_menu_keyboard,
    orders_list_keyboard,
    order_card_keyboard,
    reminder_time_keyboard
)

__all__ = [
    # Utils
    'debug_print',
    'check_permission',
    'format_phone_compact',
    'track_navigation_message',
    'track_order_file_message',
    'cleanup_order_files',
    'cleanup_all_navigation',
    'update_navigation_message',
    'safe_edit_message',
    'safe_delete_message',

    # State
    'get_navigation_message_id',
    'set_navigation_message_id',
    'remove_navigation_message_id',
    'add_order_file_message',
    'get_order_file_messages',
    'clear_order_file_messages',
    'clear_all_user_files',

    # Keyboards
    'main_menu_keyboard',
    'stats_keyboard',
    'back_to_menu_keyboard',
    'orders_list_keyboard',
    'order_card_keyboard',
    'reminder_time_keyboard'
]