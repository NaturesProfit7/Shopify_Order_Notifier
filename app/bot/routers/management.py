# app/bot/routers/management.py - ПОЛНОЕ ИГНОРИРОВАНИЕ НЕАВТОРИЗОВАННЫХ
"""Роутер для управления заказами: комментарии, напоминания"""

from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.db import get_session
from app.models import Order, OrderStatus, OrderStatusHistory

from .shared import (
    debug_print,
    check_permission,
    track_order_file_message
)

router = Router()


# FSM состояния для ввода комментария
class CommentStates(StatesGroup):
    waiting_for_comment = State()


@router.callback_query(F.data.contains(":comment"))
async def on_comment_button(callback: CallbackQuery, state: FSMContext):
    """Кнопка 'Коментар' - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"Comment request for order {order_id} from authorized user {callback.from_user.id}")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        display_order_no = order.order_number or order.id

    await state.set_state(CommentStates.waiting_for_comment)
    await state.update_data(order_id=order_id, original_message_id=callback.message.message_id)

    prompt_msg = await callback.bot.send_message(
        callback.message.chat.id,
        f"💬 Введіть коментар до замовлення #{display_order_no}:"
    )

    await state.update_data(prompt_message_id=prompt_msg.message_id)
    debug_print(f"Comment prompt sent with ID: {prompt_msg.message_id}")

    await callback.answer("💬 Очікую ваш коментар")


@router.message(CommentStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext):
    """Обработка введенного комментария - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(message.from_user.id):
        await state.clear()
        return

    debug_print(f"Received comment message from authorized user {message.from_user.id}")

    data = await state.get_data()
    order_id = data.get("order_id")
    original_message_id = data.get("original_message_id")
    prompt_message_id = data.get("prompt_message_id")

    comment_text = message.text
    debug_print(f"Processing comment for order {order_id}: '{comment_text[:50]}...'")

    try:
        with get_session() as session:
            order = session.get(Order, order_id)
            if not order:
                debug_print("Order not found")
                await message.reply("❌ Замовлення не знайдено")
                await state.clear()
                return

            display_order_no = order.order_number or order.id

            order.comment = comment_text

            history = OrderStatusHistory(
                order_id=order_id,
                old_status=order.status.value,
                new_status=order.status.value,
                changed_by_user_id=message.from_user.id,
                changed_by_username=message.from_user.username or message.from_user.first_name,
                comment=comment_text
            )
            session.add(history)
            session.commit()

            try:
                from .orders import build_order_card_message
                from .shared import order_card_keyboard

                new_text = build_order_card_message(order, detailed=True)
                keyboard = order_card_keyboard(order)

                await message.bot.edit_message_text(
                    new_text,
                    chat_id=message.chat.id,
                    message_id=original_message_id,
                    reply_markup=keyboard
                )
                debug_print("Order card updated successfully")
            except Exception as e:
                debug_print(f"Failed to update order card: {e}", "WARN")

            notification = f'✅ Коментар "{comment_text}" додано до замовлення #{display_order_no}'
            notification_msg = await message.bot.send_message(message.chat.id, notification)

            track_order_file_message(message.from_user.id, order_id, notification_msg.message_id)

            try:
                if prompt_message_id:
                    await message.bot.delete_message(message.chat.id, prompt_message_id)
                    debug_print(f"Deleted prompt message {prompt_message_id}")

                await message.bot.delete_message(message.chat.id, message.message_id)
                debug_print(f"Deleted user message {message.message_id}")
            except Exception as e:
                debug_print(f"Failed to delete messages: {e}", "WARN")

    except Exception as e:
        debug_print(f"Error processing comment: {e}", "ERROR")
        await message.reply(f"❌ Помилка обробки коментаря: {str(e)}")

    finally:
        await state.clear()
        debug_print("Comment processing completed")


@router.callback_query(F.data.contains(":reminder"))
async def on_reminder_button(callback: CallbackQuery):
    """Кнопка 'Нагадати' - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"Reminder setup for order {order_id} from authorized user {callback.from_user.id}")

    from .shared import reminder_time_keyboard
    keyboard = reminder_time_keyboard(order_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer("⏰ Оберіть час нагадування")
    except Exception as e:
        debug_print(f"Failed to show reminder keyboard: {e}", "WARN")
        await callback.answer("⏰ Оберіть час нагадування", show_alert=True)


@router.callback_query(F.data.startswith("reminder:"))
async def handle_reminder_time(callback: CallbackQuery):
    """Обработка выбора времени напоминания - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    parts = callback.data.split(":")
    order_id = int(parts[1])
    minutes = int(parts[2])

    debug_print(f"Setting reminder for order {order_id}: {minutes} minutes")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        order.reminder_at = datetime.utcnow() + timedelta(minutes=minutes)
        session.commit()

        try:
            from .orders import build_order_card_message
            from .shared import order_card_keyboard

            message_text = build_order_card_message(order, detailed=True)
            keyboard = order_card_keyboard(order)

            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except Exception as e:
            debug_print(f"Failed to update order card after reminder: {e}", "WARN")

        if minutes < 60:
            time_text = f"{minutes} хвилин"
        elif minutes < 1440:
            time_text = f"{minutes // 60} годин"
        else:
            time_text = "завтра"

        await callback.answer(f"✅ Нагадування встановлено через {time_text}")