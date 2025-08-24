# app/bot/routers/webhook.py - ПОЛНОЕ ИГНОРИРОВАНИЕ НЕАВТОРИЗОВАННЫХ
"""Роутер для обработки webhook заказов с кнопкой 'Закрити'"""

from aiogram import Router, F
from aiogram.types import CallbackQuery

from .shared import (
    debug_print,
    check_permission,
    get_webhook_messages,
    clear_webhook_messages,
    get_order_file_messages,
    clear_order_file_messages
)

router = Router()


async def cleanup_webhook_order(bot, order_id: int, chat_id: int) -> None:
    """Удаляем сообщения webhook заказа и связанные файлы только для текущего чата"""
    debug_print(f"🧹 WEBHOOK CLEANUP START: order {order_id} chat {chat_id}")

    # 1. Получаем все webhook сообщения заказа для конкретного чата
    webhook_messages = get_webhook_messages(order_id, chat_id)
    total_webhook = len(webhook_messages)
    debug_print(f"🧹 Found {total_webhook} webhook messages for chat {chat_id}")

    # 2. Удаляем webhook сообщения
    deleted_count = 0
    for msg_id in webhook_messages:
        try:
            debug_print(f"🧹 Deleting webhook message {msg_id} for chat {chat_id}...")
            await bot.delete_message(chat_id, msg_id)
            deleted_count += 1
            debug_print(f"✅ Deleted webhook message {msg_id} for chat {chat_id}")
        except Exception as e:
            debug_print(
                f"❌ Failed to delete webhook message {msg_id} for chat {chat_id}: {e}",
                "WARN",
            )

    clear_webhook_messages(order_id, chat_id)

    # 3. Удаляем файловые сообщения заказа для текущего пользователя
    file_deleted = 0
    file_messages = get_order_file_messages(chat_id, order_id)
    for msg_id in file_messages:
        try:
            debug_print(f"🧹 Deleting file message {msg_id} for user {chat_id}...")
            await bot.delete_message(chat_id, msg_id)
            file_deleted += 1
            debug_print(f"✅ Deleted file message {msg_id} for user {chat_id}")
        except Exception as e:
            debug_print(
                f"❌ Failed to delete file message {msg_id} for user {chat_id}: {e}",
                "WARN",
            )
    clear_order_file_messages(chat_id, order_id)

    debug_print(
        f"🧹 WEBHOOK CLEANUP COMPLETE: Deleted {deleted_count} webhook and {file_deleted} file messages for order {order_id} in chat {chat_id}"
    )


@router.callback_query(F.data.startswith("webhook:") & F.data.contains(":close"))
async def on_webhook_close(callback: CallbackQuery):
    """Кнопка 'Закрити' для webhook заказов - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Некоректні дані", show_alert=True)
        return

    order_id = int(parts[1])
    debug_print(f"🚨 WEBHOOK CLOSE: order {order_id} from authorized user {callback.from_user.id}")

    # Удаляем ВСЕ сообщения этого webhook заказа
    await cleanup_webhook_order(
        callback.bot,
        order_id,
        callback.from_user.id,
    )

    # Отвечаем на callback (чтобы убрать "часики" в Telegram)
    await callback.answer("✅ Замовлення закрито")

    debug_print(f"✅ Webhook order {order_id} completely closed by authorized user {callback.from_user.id}")


# УДАЛЕНЫ ПРОБЛЕМНЫЕ ОБРАБОТЧИКИ
# Они конфликтовали с основными роутерами orders.py и management.py
# Теперь webhook роутер обрабатывает ТОЛЬКО кнопку "Закрити" с полным игнорированием неавторизованных