# app/bot/routers/shared/utils.py - ИСПРАВЛЕННЫЙ ФАЙЛ
"""Общие утилиты для работы с ботом - БЕЗ ЦИКЛИЧЕСКИХ ИМПОРТОВ"""

import os
from typing import TYPE_CHECKING
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from app.bot.services.message_builder import DIVIDER

if TYPE_CHECKING:
    from app.models import Order

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
    clear_all_user_files,
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
    """
    УЖЕСТОЧЕННАЯ проверка прав доступа.
    Если список TELEGRAM_ALLOWED_USER_IDS задан - доступ ТОЛЬКО для указанных ID.
    Если список пустой - доступа НЕТ ни у кого (безопасность по умолчанию).
    """
    allowed_ids_str = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()

    # Если переменная не задана или пустая - доступа НЕТ ни у кого
    if not allowed_ids_str:
        debug_print(f"🔇 SILENT BLOCK: No allowed users configured", "WARN")
        return False

    try:
        allowed = [int(uid.strip()) for uid in allowed_ids_str.split(",") if uid.strip()]

        # Если список не удалось распарсить - доступа НЕТ
        if not allowed:
            debug_print(f"🔇 SILENT BLOCK: Failed to parse allowed users list", "WARN")
            return False

        is_allowed = user_id in allowed

        if is_allowed:
            debug_print(f"✅ ACCESS GRANTED: User {user_id} is authorized")
        else:
            debug_print(f"🔇 SILENT BLOCK: User {user_id} ignored (not in allowed list)", "WARN")

        return is_allowed

    except Exception as e:
        debug_print(f"🔇 SILENT BLOCK: Error checking permissions for user {user_id}: {e}", "ERROR")
def format_phone_compact(e164: str) -> str:
    """Форматирует телефон компактно без пробелов"""
    if not e164:
        return "Не вказано"
    return e164


def is_coming_from_order_card(message) -> bool:
    """Проверяем, идет ли переход из карточки заказа"""
    if not message or not message.text:
        return False

    # Карточка заказа содержит специфический текст
    text = message.text
    return (
            "Замовлення #" in text and
            DIVIDER in text and
            ("📱" in text or "👤" in text)
    )


def is_webhook_order_message(message) -> bool:
    """
    НОВАЯ ФУНКЦИЯ: Проверяем, является ли сообщение webhook заказом
    по наличию кнопки 'Закрити' с callback_data 'webhook:*:close'
    """
    if not message or not message.reply_markup:
        return False

    # Проверяем все кнопки в клавиатуре
    for row in message.reply_markup.inline_keyboard:
        for button in row:
            if (button.callback_data and
                    "webhook:" in button.callback_data and
                    ":close" in button.callback_data):
                debug_print(f"Found webhook close button: {button.callback_data}")
                return True

    debug_print("No webhook close button found - regular order card")
    return False


def get_webhook_order_keyboard(order: 'Order') -> InlineKeyboardMarkup:
    """
    НОВАЯ ФУНКЦИЯ: Клавиатура для webhook заказов - ВСЕГДА с кнопкой 'Закрити'
    ИМПОРТИРУЕМ OrderStatus ЛОКАЛЬНО чтобы избежать циклических импортов
    """
    from app.models import OrderStatus

    buttons = []

    # Кнопки статуса
    if order.status == OrderStatus.NEW:
        buttons.append([
            InlineKeyboardButton(text="✅ Зв'язались", callback_data=f"order:{order.id}:contacted"),
            InlineKeyboardButton(text="❌ Скасування", callback_data=f"order:{order.id}:cancel")
        ])
    elif order.status == OrderStatus.WAITING_PAYMENT:
        buttons.append([
            InlineKeyboardButton(text="💰 Оплатили", callback_data=f"order:{order.id}:paid"),
            InlineKeyboardButton(text="❌ Скасування", callback_data=f"order:{order.id}:cancel")
        ])

    # Файлы
    buttons.append([
        InlineKeyboardButton(text="📄 PDF", callback_data=f"order:{order.id}:resend:pdf"),
        InlineKeyboardButton(text="📱 VCF", callback_data=f"order:{order.id}:resend:vcf")
    ])

    # Реквизиты
    buttons.append([
        InlineKeyboardButton(text="💳 Реквізити", callback_data=f"order:{order.id}:payment")
    ])

    # Дополнительные действия (для активных заказов)
    if order.status in [OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]:
        buttons.append([
            InlineKeyboardButton(text="💬 Коментар", callback_data=f"order:{order.id}:comment"),
            InlineKeyboardButton(text="⏰ Нагадати", callback_data=f"order:{order.id}:reminder")
        ])

    # CRM-кнопка для оплачених замовлень
    if order.status == OrderStatus.PAID:
        crm_id = (order.raw_json or {}).get("_crm_order_id")
        if crm_id:
            buttons.append([
                InlineKeyboardButton(text="✅ В CRM", callback_data="noop")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(text="🏪 Створити в CRM", callback_data=f"order:{order.id}:create_crm")
            ])

    # ВСЕГДА кнопка "Закрити" для webhook заказов
    buttons.append([
        InlineKeyboardButton(text="❌ Закрити", callback_data=f"webhook:{order.id}:close")
    ])

    debug_print(f"Created webhook keyboard for order {order.id} with {len(buttons)} rows")
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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


async def cleanup_all_user_order_files(bot, chat_id: int, user_id: int) -> None:
    """Удаляем ВСЕ файловые сообщения пользователя (всех заказов)"""
    debug_print(f"🧹 UNIVERSAL CLEANUP START: user {user_id}")

    files_to_delete = clear_all_user_files(user_id)

    deleted_count = 0
    total_count = 0

    for order_id, message_ids in files_to_delete.items():
        debug_print(f"🧹 Order {order_id}: {len(message_ids)} files to delete")

        for msg_id in message_ids:
            total_count += 1
            try:
                await bot.delete_message(chat_id, msg_id)
                deleted_count += 1
                debug_print(f"✅ Deleted file message {msg_id} (order {order_id})")
            except Exception as e:
                debug_print(f"❌ Failed to delete file message {msg_id}: {e}", "WARN")

    debug_print(f"🧹 UNIVERSAL CLEANUP COMPLETE: Deleted {deleted_count}/{total_count} file messages")


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
