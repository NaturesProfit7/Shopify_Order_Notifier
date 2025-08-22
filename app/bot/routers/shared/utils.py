# app/bot/routers/shared/utils.py - ОБНОВЛЕННАЯ ВЕРСИЯ
"""Общие утилиты для работы с ботом"""

import os
from aiogram.types import InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from .state import (
    get_navigation_message_id,
    set_navigation_message_id,
    remove_navigation_message_id,
    add_order_file_message,
    get_order_file_messages,
    clear_order_file_messages,
    add_navigation_message,
    get_all_navigation_messages,
    clear_all_navigation_messages,
    remove_navigation_message,
    # НОВЫЕ функции для webhook
    add_webhook_message,
    get_webhook_messages,
    clear_webhook_messages,
    is_webhook_message,
    get_order_by_webhook_message
)


def debug_print(message: str, level: str = "INFO") -> None:
    """Отладочные сообщения"""
    print(f"🤖 BOT {level}: {message}")


def check_permission(user_id: int) -> bool:
    """Проверка прав доступа"""
    allowed_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    allowed = [int(uid.strip()) for uid in allowed_ids.split(",") if uid.strip()]
    return not allowed or user_id in allowed


def format_phone_compact(e164: str) -> str:
    """Форматирует телефон компактно без пробелов"""
    if not e164:
        return "Не вказано"
    return e164


def track_navigation_message(user_id: int, message_id: int) -> None:
    """Отслеживаем основное навигационное сообщение пользователя"""
    debug_print(f"Tracking navigation message for user {user_id}: {message_id}")
    set_navigation_message_id(user_id, message_id)
    add_navigation_message(user_id, message_id)
    debug_print(f"Navigation message set successfully")


def track_order_file_message(user_id: int, order_id: int, message_id: int) -> None:
    """Отслеживаем файловые сообщения заказа"""
    debug_print(f"📌 TRACKING: user {user_id}, order {order_id}, message {message_id}")
    add_order_file_message(user_id, order_id, message_id)

    tracked_messages = get_order_file_messages(user_id, order_id)
    debug_print(f"📌 Now tracking {len(tracked_messages)} messages for order {order_id}: {list(tracked_messages)}")


async def cleanup_all_navigation(bot, chat_id: int, user_id: int) -> None:
    """Удаляем ВСЕ навигационные сообщения пользователя"""
    debug_print(f"🧹 NAVIGATION CLEANUP START: user {user_id}")
    message_ids = get_all_navigation_messages(user_id)
    debug_print(f"🧹 Found {len(message_ids)} navigation messages to delete: {list(message_ids)}")

    deleted_count = 0
    for msg_id in message_ids:
        try:
            debug_print(f"🧹 Deleting navigation message {msg_id}...")
            await bot.delete_message(chat_id, msg_id)
            deleted_count += 1
            debug_print(f"✅ Deleted navigation message {msg_id}")
        except Exception as e:
            debug_print(f"❌ Failed to delete navigation message {msg_id}: {e}", "WARN")

    clear_all_navigation_messages(user_id)
    debug_print(f"🧹 NAVIGATION CLEANUP COMPLETE: Deleted {deleted_count}/{len(message_ids)} navigation messages")


async def cleanup_order_files(bot, chat_id: int, user_id: int, order_id: int) -> None:
    """Удаляем все файловые сообщения конкретного заказа"""
    debug_print(f"🧹 CLEANUP START: user {user_id}, order {order_id}")
    message_ids = get_order_file_messages(user_id, order_id)
    debug_print(f"🧹 Found {len(message_ids)} messages to delete: {list(message_ids)}")

    deleted_count = 0
    for msg_id in message_ids:
        try:
            debug_print(f"🧹 Deleting message {msg_id}...")
            await bot.delete_message(chat_id, msg_id)
            deleted_count += 1
            debug_print(f"✅ Deleted message {msg_id}")
        except Exception as e:
            debug_print(f"❌ Failed to delete message {msg_id}: {e}", "WARN")

    clear_order_file_messages(user_id, order_id)
    debug_print(f"🧹 CLEANUP COMPLETE: Deleted {deleted_count}/{len(message_ids)} messages for order {order_id}")
    debug_print(f"🧹 Cleared tracking for user {user_id}, order {order_id}")


async def update_navigation_message(bot, chat_id: int, user_id: int, text: str,
                                    reply_markup: InlineKeyboardMarkup = None) -> bool:
    """Обновляем основное навигационное сообщение пользователя"""
    last_message_id = get_navigation_message_id(user_id)
    debug_print(f"Updating navigation for user {user_id}, last_message_id: {last_message_id}")

    if last_message_id:
        try:
            debug_print(f"Attempting to edit message {last_message_id}")
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=last_message_id,
                reply_markup=reply_markup
            )
            debug_print(f"Successfully edited message {last_message_id}")
            add_navigation_message(user_id, last_message_id)
            return True
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                debug_print(f"Message {last_message_id} content is the same, no update needed")
                return True
            else:
                debug_print(f"Failed to edit message {last_message_id}: {e}", "WARN")
                remove_navigation_message_id(user_id)
        except Exception as e:
            debug_print(f"Failed to edit message {last_message_id}: {e}", "WARN")
            remove_navigation_message_id(user_id)

    debug_print(f"Sending new navigation message for user {user_id}")
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup
        )
        track_navigation_message(user_id, message.message_id)
        debug_print(f"Sent new message with ID: {message.message_id}")
        return True
    except Exception as e:
        debug_print(f"Failed to send new message: {e}", "ERROR")
        return False


async def safe_edit_message(bot, chat_id: int, message_id: int, text: str,
                            reply_markup: InlineKeyboardMarkup = None) -> bool:
    """Безопасное редактирование сообщения"""
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup
        )
        return True
    except (TelegramBadRequest, Exception) as e:
        debug_print(f"Failed to edit message {message_id}: {e}", "WARN")
        return False


async def safe_delete_message(bot, chat_id: int, message_id: int) -> bool:
    """Безопасное удаление сообщения"""
    try:
        await bot.delete_message(chat_id, message_id)
        return True
    except Exception as e:
        debug_print(f"Failed to delete message {message_id}: {e}", "WARN")
        return False