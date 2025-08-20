# app/bot/handlers/callbacks.py
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.db import get_session
from app.models import Order, OrderStatus, OrderStatusHistory
from app.bot.keyboards import get_order_keyboard, get_reminder_keyboard
from app.bot.services.message_builder import build_order_message
import os

router = Router()


# FSM состояния для ввода комментария
class CommentStates(StatesGroup):
    waiting_for_comment = State()


def check_permission(user_id: int) -> bool:
    """Проверка прав доступа"""
    allowed_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    allowed = [int(uid.strip()) for uid in allowed_ids.split(",") if uid.strip()]
    return user_id in allowed


@router.callback_query(F.data.startswith("order:"))
async def handle_order_action(callback: CallbackQuery, state: FSMContext):
    """Обработка действий с заказом"""

    # Проверяем права
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("❌ Некоректні дані", show_alert=True)
        return

    order_id = int(parts[1])
    action = parts[2]

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        old_status = order.status

        # Обработка действий
        if action == "contacted":
            if order.status != OrderStatus.NEW:
                await callback.answer("⚠️ Неможливо змінити статус", show_alert=True)
                return

            order.status = OrderStatus.WAITING_PAYMENT
            order.processed_by_user_id = callback.from_user.id
            order.processed_by_username = callback.from_user.username or callback.from_user.first_name

            # Добавляем в историю
            history = OrderStatusHistory(
                order_id=order_id,
                old_status=old_status.value,
                new_status=OrderStatus.WAITING_PAYMENT.value,
                changed_by_user_id=callback.from_user.id,
                changed_by_username=callback.from_user.username or callback.from_user.first_name
            )
            session.add(history)
            session.commit()

            # Обновляем сообщение
            new_text = build_order_message(order)
            new_keyboard = get_order_keyboard(order)

            await callback.message.edit_text(
                new_text,
                reply_markup=new_keyboard
            )

            await callback.answer("✅ Статус змінено: Очікує оплату")

            # Отправляем уведомление в чат
            notification = (
                f"📝 <b>Зміна статусу</b>\n"
                f"Замовлення №{order.order_number or order.id}\n"
                f"Новий статус: Очікує оплату\n"
                f"Менеджер: @{callback.from_user.username or callback.from_user.first_name}"
            )
            await callback.bot.send_message(callback.message.chat.id, notification)

        elif action == "paid":
            if order.status != OrderStatus.WAITING_PAYMENT:
                await callback.answer("⚠️ Неможливо змінити статус", show_alert=True)
                return

            order.status = OrderStatus.PAID

            # Добавляем в историю
            history = OrderStatusHistory(
                order_id=order_id,
                old_status=old_status.value,
                new_status=OrderStatus.PAID.value,
                changed_by_user_id=callback.from_user.id,
                changed_by_username=callback.from_user.username or callback.from_user.first_name
            )
            session.add(history)
            session.commit()

            # Обновляем сообщение
            new_text = build_order_message(order)
            new_keyboard = get_order_keyboard(order)

            await callback.message.edit_text(
                new_text,
                reply_markup=new_keyboard
            )

            await callback.answer("✅ Статус змінено: Оплачено")

            # Отправляем уведомление
            notification = (
                f"💰 <b>Замовлення оплачено!</b>\n"
                f"Замовлення №{order.order_number or order.id}\n"
                f"Менеджер: @{callback.from_user.username or callback.from_user.first_name}"
            )
            await callback.bot.send_message(callback.message.chat.id, notification)

        elif action == "cancel":
            order.status = OrderStatus.CANCELLED

            # Добавляем в историю
            history = OrderStatusHistory(
                order_id=order_id,
                old_status=old_status.value,
                new_status=OrderStatus.CANCELLED.value,
                changed_by_user_id=callback.from_user.id,
                changed_by_username=callback.from_user.username or callback.from_user.first_name
            )
            session.add(history)
            session.commit()

            # Обновляем сообщение
            new_text = build_order_message(order)
            new_keyboard = get_order_keyboard(order)

            await callback.message.edit_text(
                new_text,
                reply_markup=new_keyboard
            )

            await callback.answer("❌ Замовлення скасовано")

            # Отправляем уведомление
            notification = (
                f"❌ <b>Замовлення скасовано</b>\n"
                f"Замовлення №{order.order_number or order.id}\n"
                f"Менеджер: @{callback.from_user.username or callback.from_user.first_name}"
            )
            await callback.bot.send_message(callback.message.chat.id, notification)

        elif action == "comment":
            # Запускаем FSM для ввода комментария
            await state.set_state(CommentStates.waiting_for_comment)
            await state.update_data(order_id=order_id, message_id=callback.message.message_id)

            await callback.answer("💬 Відправте коментар до замовлення")
            await callback.bot.send_message(
                callback.message.chat.id,
                f"💬 Введіть коментар до замовлення №{order.order_number or order.id}:",
                reply_to_message_id=callback.message.message_id
            )

        elif action == "reminder":
            # Показываем кнопки выбора времени
            keyboard = get_reminder_keyboard(order_id)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
            await callback.answer("⏰ Оберіть час нагадування")

        elif action == "show":
            # Показываем детальную информацию
            details = build_order_message(order, detailed=True)
            await callback.answer(details, show_alert=True)


@router.callback_query(F.data.startswith("reminder:"))
async def handle_reminder_time(callback: CallbackQuery):
    """Обработка выбора времени напоминания"""

    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    parts = callback.data.split(":")
    order_id = int(parts[1])
    minutes = int(parts[2])

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Устанавливаем время напоминания
        order.reminder_at = datetime.utcnow() + timedelta(minutes=minutes)
        session.commit()

        # Возвращаем исходные кнопки
        keyboard = get_order_keyboard(order)
        await callback.message.edit_reply_markup(reply_markup=keyboard)

        await callback.answer(f"✅ Нагадування встановлено через {minutes} хвилин")


@router.message(CommentStates.waiting_for_comment)
async def process_comment(message, state: FSMContext):
    """Обработка введенного комментария"""

    if not check_permission(message.from_user.id):
        await message.reply("❌ У вас немає прав для цієї дії")
        await state.clear()
        return

    data = await state.get_data()
    order_id = data.get("order_id")
    original_message_id = data.get("message_id")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await message.reply("❌ Замовлення не знайдено")
            await state.clear()
            return

        # Сохраняем комментарий
        order.comment = message.text

        # Добавляем в историю
        history = OrderStatusHistory(
            order_id=order_id,
            old_status=order.status.value,
            new_status=order.status.value,
            changed_by_user_id=message.from_user.id,
            changed_by_username=message.from_user.username or message.from_user.first_name,
            comment=message.text
        )
        session.add(history)
        session.commit()

        # Обновляем исходное сообщение
        new_text = build_order_message(order)
        keyboard = get_order_keyboard(order)

        try:
            await message.bot.edit_message_text(
                new_text,
                chat_id=message.chat.id,
                message_id=original_message_id,
                reply_markup=keyboard
            )
        except:
            pass  # Сообщение могло быть уже изменено

        await message.reply(f"✅ Коментар додано до замовлення №{order.order_number or order.id}")

    await state.clear()