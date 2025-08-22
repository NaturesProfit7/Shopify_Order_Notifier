# app/bot/routers/shared/__init__.py - ОБНОВЛЕННЫЙ
"""Общие компоненты для роутеров бота"""

from .utils import (
    debug_print,
    check_permission,
    format_phone_compact,
    track_navigation_message,
    track_order_file_message,
    cleanup_order_files,
    cleanup_all_navigation,
    cleanup_all_user_order_files,  # НОВАЯ ФУНКЦИЯ
    is_coming_from_order_card,     # НОВАЯ ФУНКЦИЯ
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
    clear_all_user_files,
    # НОВЫЕ функции для webhook
    add_webhook_message,
    get_webhook_messages,
    clear_webhook_messages,
    is_webhook_message,
    get_order_by_webhook_message,
    user_order_files  # Экспортируем для webhook роутера
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
    'cleanup_all_user_order_files',  # ДОБАВЛЕНО
    'is_coming_from_order_card',     # ДОБАВЛЕНО
    'update_navigation_message',
    'safe_edit_message',
    'safe_delete_message',

    # State - базовые
    'get_navigation_message_id',
    'set_navigation_message_id',
    'remove_navigation_message_id',
    'add_order_file_message',
    'get_order_file_messages',
    'clear_order_file_messages',
    'clear_all_user_files',

    # State - webhook
    'add_webhook_message',
    'get_webhook_messages',
    'clear_webhook_messages',
    'is_webhook_message',
    'get_order_by_webhook_message',
    'user_order_files',

    # Keyboards
    'main_menu_keyboard',
    'stats_keyboard',
    'back_to_menu_keyboard',
    'orders_list_keyboard',
    'order_card_keyboard',
    'reminder_time_keyboard'
]