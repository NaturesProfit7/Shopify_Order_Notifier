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


async def cleanup_webhook_order(bot, chat_id: int, order_id: int) -> None:
    """Удаляем ВСЕ сообщения webhook заказа: карточку + файлы"""
    debug_print(f"🧹 WEBHOOK CLEANUP START: order {order_id}")

    # 1. Получаем все webhook сообщения заказа
    webhook_messages = get_webhook_messages(order_id)
    debug_print(f"🧹 Found {len(webhook_messages)} webhook messages: {list(webhook_messages)}")

    # 2. Получаем все файловые сообщения заказа (от всех пользователей)
    from .shared import user_order_files
    all_file_messages = set()

    for user_id in user_order_files:
        file_messages = get_order_file_messages(user_id, order_id)
        all_file_messages.update(file_messages)
        debug_print(f"🧹 User {user_id} has {len(file_messages)} file messages for order {order_id}")

    debug_print(f"🧹 Total file messages to delete: {len(all_file_messages)}")

    # 3. Удаляем все сообщения
    deleted_count = 0
    all_messages = webhook_messages | all_file_messages

    for msg_id in all_messages:
        try:
            debug_print(f"🧹 Deleting message {msg_id}...")
            await bot.delete_message(chat_id, msg_id)
            deleted_count += 1
            debug_print(f"✅ Deleted message {msg_id}")
        except Exception as e:
            debug_print(f"❌ Failed to delete message {msg_id}: {e}", "WARN")

    # 4. Очищаем трекинг
    clear_webhook_messages(order_id)

    # Очищаем файловые сообщения для всех пользователей
    for user_id in list(user_order_files.keys()):
        clear_order_file_messages(user_id, order_id)

    debug_print(
        f"🧹 WEBHOOK CLEANUP COMPLETE: Deleted {deleted_count}/{len(all_messages)} messages for order {order_id}")


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
        callback.message.chat.id,
        order_id
    )

    # Отвечаем на callback (чтобы убрать "часики" в Telegram)
    await callback.answer("✅ Замовлення закрито")

    debug_print(f"✅ Webhook order {order_id} completely closed by authorized user {callback.from_user.id}")


# УДАЛЕНЫ ПРОБЛЕМНЫЕ ОБРАБОТЧИКИ
# Они конфликтовали с основными роутерами orders.py и management.py
# Теперь webhook роутер обрабатывает ТОЛЬКО кнопку "Закрити" с полным игнорированием неавторизованных