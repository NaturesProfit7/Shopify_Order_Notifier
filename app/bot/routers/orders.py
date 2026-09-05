# app/bot/routers/orders.py - ОПТИМИЗИРОВАННАЯ ВЕРСИЯ С БЫСТРЫМИ РЕКВИЗИТАМИ
"""Роутер для работы с заказами: просмотр, изменение статусов, отправка файлов"""

import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Order, OrderStatus, OrderStatusHistory
from app.bot.services.message_builder import get_status_emoji, get_status_text, DIVIDER
from app.services.pdf_service import build_order_pdf
from app.services.vcf_service import build_contact_vcf

from .shared import (
    debug_print,
    check_permission,
    format_phone_compact,
    track_order_file_message,
    cleanup_order_files,
    get_order_file_messages,
    order_card_keyboard,
    is_webhook_order_message,
    get_webhook_order_keyboard,
    get_webhook_messages
)

PAYMENT_MESSAGE_DELAY = 1  # seconds to wait between payment messages

router = Router()


class OrderLockError(Exception):
    """Исключение при блокировке заказа"""
    pass


class StatusChangeError(Exception):
    """Исключение при изменении статуса"""
    pass


def build_order_card_message(order: Order, detailed: bool = False) -> str:
    """Построить сообщение карточки заказа"""
    order_no = order.order_number or order.id
    status_emoji = get_status_emoji(order.status)
    status_text = get_status_text(order.status)

    customer_name = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"
    phone = format_phone_compact(order.customer_phone_e164)

    message = f"""📦 <b>Замовлення #{order_no}</b> • {status_emoji} {status_text}
{DIVIDER}
👤 {customer_name}
📱 {phone}"""

    if detailed and order.raw_json:
        data = order.raw_json

        # Товары
        items = data.get("line_items", [])
        if items:
            items_text = []
            for item in items[:5]:
                title = item.get("title", "")
                qty = item.get("quantity", 0)
                items_text.append(f"• {title} x{qty}")

            if items_text:
                message += f"\n🛍 <b>Товари:</b> {', '.join(items_text)}"
                if len(items) > 5:
                    message += f" <i>+ще {len(items) - 5}</i>"

        # Доставка
        shipping = data.get("shipping_address", {})
        if shipping:
            city = shipping.get("city", "")
            address = shipping.get("address1", "")
            if city or address:
                delivery_parts = [p for p in [city, address] if p]
                message += f"\n📍 <b>Доставка:</b> {', '.join(delivery_parts)}"

        # Сумма
        total = data.get("total_price", "")
        currency = data.get("currency", "UAH")
        if total:
            message += f"\n💰 <b>Сума:</b> {total} {currency}"

    message += f"\n{DIVIDER}"

    # Дополнительная информация
    if order.comment:
        message += f"\n💬 <i>Коментар: {order.comment}</i>"

    if order.reminder_at:
        reminder_time = order.reminder_at.strftime("%d.%m %H:%M")
        message += f"\n⏰ <i>Нагадування: {reminder_time}</i>"

    if order.processed_by_username:
        message += f"\n👨‍💼 <i>Менеджер: @{order.processed_by_username}</i>"

    return message


def get_correct_keyboard(order: Order, callback_message) -> any:
    """Выбирает правильную клавиатуру в зависимости от источника заказа"""
    if is_webhook_order_message(callback_message):
        debug_print(f"Using webhook keyboard for order {order.id}")
        return get_webhook_order_keyboard(order)
    else:
        debug_print(f"Using regular keyboard for order {order.id}")
        return order_card_keyboard(order)


def change_order_status_atomic(
        session: Session,
        order_id: int,
        expected_status: OrderStatus,
        new_status: OrderStatus,
        user_id: int,
        username: str = None
) -> tuple[bool, Order, str]:
    """
    АТОМАРНОЕ изменение статуса заказа с проверкой ожидаемого состояния.

    Returns:
        (success, order_object, error_message)
    """
    debug_print(f"🔄 ATOMIC STATUS CHANGE: order {order_id}, {expected_status.value} -> {new_status.value}")

    try:
        # Получаем заказ с блокировкой строки (FOR UPDATE)
        order = session.query(Order).filter(Order.id == order_id).with_for_update().first()

        if not order:
            return False, None, "Замовлення не знайдено"

        # Проверяем текущий статус
        if order.status != expected_status:
            current_status_text = get_status_text(order.status)
            expected_status_text = get_status_text(expected_status)

            debug_print(f"❌ STATUS CONFLICT: expected {expected_status.value}, got {order.status.value}")

            return False, order, (
                f"Статус змінився!\n"
                f"Очікувався: {expected_status_text}\n"
                f"Поточний: {current_status_text}\n"
                f"Оновіть карточку заказу"
            )

        # Изменяем статус
        old_status = order.status
        order.status = new_status
        order.processed_by_user_id = user_id
        order.processed_by_username = username or str(user_id)
        order.updated_at = datetime.utcnow()

        # Специальная логика для WAITING_PAYMENT
        if new_status == OrderStatus.WAITING_PAYMENT and old_status == OrderStatus.NEW:
            order.waiting_payment_since = datetime.utcnow()

        # Добавляем в историю
        history = OrderStatusHistory(
            order_id=order_id,
            old_status=old_status.value,
            new_status=new_status.value,
            changed_by_user_id=user_id,
            changed_by_username=username or str(user_id)
        )
        session.add(history)

        # Коммитим изменения
        session.commit()

        debug_print(f"✅ STATUS CHANGED SUCCESSFULLY: order {order_id}, {old_status.value} -> {new_status.value}")
        return True, order, ""

    except Exception as e:
        debug_print(f"❌ ATOMIC STATUS CHANGE FAILED: {e}", "ERROR")
        session.rollback()
        return False, None, f"Помилка зміни статусу: {str(e)}"


async def notify_other_managers_about_status_change(
        bot,
        order: Order,
        old_status: OrderStatus,
        new_status: OrderStatus,
        changed_by_user_id: int,
        changed_by_username: str
):
    """
    Уведомляет других менеджеров об изменении статуса заказа.
    Обновляет их webhook карточки заказа.
    """
    debug_print(f"📢 NOTIFYING OTHER MANAGERS: order {order.id}, status change by user {changed_by_user_id}")

    # Получаем все webhook сообщения этого заказа
    webhook_messages = get_webhook_messages(order.id)
    total_messages = sum(len(msgs) for msgs in webhook_messages.values())
    debug_print(f"📢 Found {total_messages} webhook messages to update")

    if not webhook_messages:
        debug_print("📢 No webhook messages found - skipping notifications")
        return

    updated_count = 0
    for manager_id, message_ids in webhook_messages.items():
        if manager_id == changed_by_user_id:
            continue

        for message_id in message_ids:
            try:
                updated_message = build_order_card_message(order, detailed=True)
                updated_keyboard = get_webhook_order_keyboard(order)

                await bot.edit_message_text(
                    text=updated_message,
                    chat_id=manager_id,
                    message_id=message_id,
                    reply_markup=updated_keyboard
                )
                updated_count += 1
                debug_print(f"✅ Updated webhook message {message_id} for user {manager_id}")
            except Exception as e:
                debug_print(f"❌ Failed to update webhook message {message_id} for user {manager_id}: {e}", "WARN")

        try:
            old_status_text = get_status_text(old_status)
            new_status_text = get_status_text(new_status)
            order_no = order.order_number or order.id
            notification = (
                f"🔄 <b>Статус змінено</b>\n"
                f"📦 Замовлення #{order_no}\n"
                f"📈 {old_status_text} → {new_status_text}\n"
                f"👤 Менеджер: @{changed_by_username}"
            )
            await bot.send_message(manager_id, notification)
            debug_print(f"✅ Sent status change notification to user {manager_id}")
        except Exception as e:
            debug_print(f"❌ Failed to send status change notification to user {manager_id}: {e}", "WARN")

    debug_print(f"📢 NOTIFICATION COMPLETE: Updated {updated_count}/{total_messages} messages")


@router.callback_query(F.data.regexp(r"^order:\d+:view$"))
async def on_order_view(callback: CallbackQuery):
    """Показать карточку заказа - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"Order view callback: order {order_id} from authorized user {callback.from_user.id}")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        message_text = build_order_card_message(order, detailed=True)
        keyboard = order_card_keyboard(order)

        try:
            await callback.message.edit_text(
                text=message_text,
                reply_markup=keyboard
            )
        except Exception as e:
            debug_print(f"Failed to edit message: {e}", "WARN")

    await callback.answer()


@router.callback_query(F.data.regexp(r"^order:\d+:back_to_list$"))
async def on_back_to_list(callback: CallbackQuery):
    """Кнопка 'До списку' - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"🔙 BACK TO LIST: order {order_id}, user {callback.from_user.id}")

    tracked_before = get_order_file_messages(callback.from_user.id, order_id)
    debug_print(
        f"🧹 Cleaning up {len(tracked_before)} messages: {list(tracked_before)}")

    await cleanup_order_files(
        callback.bot,
        callback.message.chat.id,
        callback.from_user.id,
        order_id
    )

    remaining_after = get_order_file_messages(callback.from_user.id, order_id)
    if remaining_after:
        debug_print(
            f"⚠️ Remaining tracked messages after cleanup: {list(remaining_after)}",
            "WARN"
        )
    else:
        debug_print(f"✅ Cleaned up all files for order {order_id}")

    from .navigation import on_orders_list
    from types import SimpleNamespace

    list_callback = SimpleNamespace()
    list_callback.data = "orders:list:new:offset=0"
    list_callback.from_user = callback.from_user
    list_callback.bot = callback.bot
    list_callback.message = callback.message
    list_callback.answer = callback.answer

    debug_print(f"🔙 Switching to orders list...")
    await on_orders_list(list_callback)


@router.callback_query(F.data.contains(":resend:"))
async def on_resend_file(callback: CallbackQuery):
    """Повторная отправка PDF или VCF - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    parts = callback.data.split(":")
    order_id = int(parts[1])
    file_type = parts[3]

    debug_print(f"🎯 RESEND: {file_type} for order {order_id} from authorized user {callback.from_user.id}")

    # КРИТИЧНО: Сразу отвечаем на callback чтобы избежать timeout
    try:
        await callback.answer(f"⏳ Генерую {file_type.upper()}...")
    except Exception as e:
        debug_print(f"Failed to answer callback: {e}", "WARNING")
        # Продолжаем работу даже если не смогли ответить на callback

    await cleanup_order_files(callback.bot, callback.message.chat.id, callback.from_user.id, order_id)

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order or not order.raw_json:
            # Отправляем сообщение об ошибке в чат, т.к. callback уже отвечен
            try:
                await callback.bot.send_message(
                    callback.message.chat.id,
                    "❌ Дані замовлення не знайдено"
                )
            except Exception:
                pass
            return

        try:
            if file_type == "pdf":
                import time
                start_time = time.time()

                debug_print(f"⏳ Starting PDF generation for order {order_id}")
                # Запускаем CPU-bound операцию в отдельном потоке чтобы не блокировать event loop
                loop = asyncio.get_event_loop()
                pdf_bytes, pdf_filename = await loop.run_in_executor(
                    None, build_order_pdf, order.raw_json
                )
                pdf_generation_time = time.time() - start_time
                debug_print(f"📄 PDF generated in {pdf_generation_time:.2f}s for order {order_id}")
                
                pdf_file = BufferedInputFile(pdf_bytes, pdf_filename)

                from app.services.message_templates import render_simple_confirm_with_contact
                from app.services.address_utils import get_delivery_and_contact_info, get_contact_name

                template_start = time.time()
                _, contact_info = get_delivery_and_contact_info(order.raw_json)
                contact_first_name, contact_last_name = get_contact_name(contact_info)

                client_message = render_simple_confirm_with_contact(
                    order.raw_json,
                    contact_first_name,
                    contact_last_name
                )
                template_time = time.time() - template_start
                debug_print(f"📝 Template rendered in {template_time:.2f}s for order {order_id}")

                send_start = time.time()
                # Retry логика для отправки PDF через медленное соединение
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        pdf_msg = await callback.bot.send_document(
                            chat_id=callback.message.chat.id,
                            document=pdf_file,
                            caption=client_message,
                            request_timeout=60  # 60 секунд таймаут для отправки
                        )
                        send_time = time.time() - send_start
                        debug_print(f"📤 PDF sent in {send_time:.2f}s for order {order_id} (attempt {attempt + 1})")
                        break
                    except Exception as send_error:
                        debug_print(f"⚠️ PDF send attempt {attempt + 1} failed: {send_error}")
                        if attempt == max_retries - 1:
                            raise  # Последняя попытка - пробрасываем ошибку
                        await asyncio.sleep(2)  # Пауза перед повтором
                        # Пересоздаем файл для повторной отправки
                        pdf_file = BufferedInputFile(pdf_bytes, pdf_filename)

                track_order_file_message(callback.from_user.id, order_id, pdf_msg.message_id)
                total_time = time.time() - start_time
                debug_print(f"✅ PDF completed in {total_time:.2f}s total for order {order_id}")

            elif file_type == "vcf":
                import time
                from functools import partial
                start_time = time.time()

                debug_print(f"⏳ Starting VCF generation for order {order_id}")
                # Запускаем в отдельном потоке чтобы не блокировать event loop
                loop = asyncio.get_event_loop()
                vcf_func = partial(
                    build_contact_vcf,
                    first_name=order.customer_first_name or "",
                    last_name=order.customer_last_name or "",
                    order_id=str(order.order_number or order.id),
                    phone_e164=order.customer_phone_e164
                )
                vcf_bytes, vcf_filename = await loop.run_in_executor(None, vcf_func)
                vcf_generation_time = time.time() - start_time
                debug_print(f"📱 VCF generated in {vcf_generation_time:.2f}s for order {order_id}")
                
                vcf_file = BufferedInputFile(vcf_bytes, vcf_filename)

                caption = f"📱 Контакт клієнта • #{order.order_number or order.id}"
                if order.customer_phone_e164:
                    caption += f" • {format_phone_compact(order.customer_phone_e164)}"

                send_start = time.time()
                # Retry логика для отправки VCF через медленное соединение  
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        vcf_msg = await callback.bot.send_document(
                            chat_id=callback.message.chat.id,
                            document=vcf_file,
                            caption=caption,
                            request_timeout=60  # 60 секунд таймаут для отправки
                        )
                        send_time = time.time() - send_start
                        debug_print(f"📤 VCF sent in {send_time:.2f}s for order {order_id} (attempt {attempt + 1})")
                        break
                    except Exception as send_error:
                        debug_print(f"⚠️ VCF send attempt {attempt + 1} failed: {send_error}")
                        if attempt == max_retries - 1:
                            raise  # Последняя попытка - пробрасываем ошибку
                        await asyncio.sleep(2)  # Пауза перед повтором
                        # Пересоздаем файл для повторной отправки
                        vcf_file = BufferedInputFile(vcf_bytes, vcf_filename)

                track_order_file_message(callback.from_user.id, order_id, vcf_msg.message_id)
                total_time = time.time() - start_time
                debug_print(f"✅ VCF completed in {total_time:.2f}s total for order {order_id}")

        except Exception as e:
            debug_print(f"Error sending {file_type}: {e}", "ERROR")
            # Отправляем сообщение об ошибке в чат, т.к. callback уже отвечен
            try:
                await callback.bot.send_message(
                    callback.message.chat.id,
                    f"❌ Помилка при генерації {file_type.upper()}: {str(e)}"
                )
            except Exception:
                pass


@router.callback_query(F.data.contains(":payment"))
async def on_payment_info(callback: CallbackQuery):
    """
    ОПТИМИЗИРОВАННАЯ кнопка 'Реквізити' с полупараллельной отправкой
    Гарантирует правильный порядок сообщений и надежный трекинг
    """
    if not check_permission(callback.from_user.id):
        return

    # ВАЖНО: Сразу отвечаем на callback чтобы убрать "часики"
    await callback.answer("💳 Підготовка реквізитів...")

    order_id = int(callback.data.split(":")[1])
    debug_print(f"💳 PAYMENT: for order {order_id} - SEMI-PARALLEL VERSION")

    # Получаем данные заказа
    order_total = "800"
    currency = "грн"

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Извлекаем сумму если есть raw_json
        if order.raw_json:
            total_price = order.raw_json.get("total_price")
            order_currency = order.raw_json.get("currency", "UAH")
            if total_price:
                try:
                    order_total = str(int(float(total_price)))
                    currency = "грн" if order_currency == "UAH" else order_currency
                except:
                    pass

    # Формируем все сообщения заранее
    payment_message = f"""💳 <b>Реквізити для оплати</b>

Передаємо замовлення в роботу після предплати, так як виготовлення повністю індивідуально 

Максимальний термін виготовлення складає 7 робочих днів, одразу по готовності відправляємо замовлення Вам 🚀

🛍 <b>Сума замовлення складає - {order_total} {currency}</b>

Оплату можна здійснити на:
<b>ФОП Комарницька Катерина Сергіївна</b>
<code>UA613220010000026004340089782</code>
<b>ЕДРПОУ:</b> 3577508940
<b>Призначення:</b> Оплата за товар 

Надсилаю всю інформацію окремо, щоб вам було зручно копіювати ☺️👇"""

    # Копируемые сообщения в строгом порядке
    copy_messages = [
        "ФОП Комарницька Катерина Сергіївна",
        "UA613220010000026004340089782",
        "3577508940",
        "Оплата за товар",
    ]

    # Очищаем старые файлы
    await cleanup_order_files(callback.bot, callback.message.chat.id, callback.from_user.id, order_id)

    try:
        debug_print(f"💳 Sending payment info SEMI-PARALLEL for order {order_id}")
        start_time = asyncio.get_event_loop().time()

        # ШАГ 1: Отправляем ОСНОВНОЕ сообщение первым (гарантированно)
        main_msg = await callback.bot.send_message(
            callback.message.chat.id,
            payment_message
        )
        track_order_file_message(callback.from_user.id, order_id, main_msg.message_id)
        debug_print(f"✅ Main message sent and tracked: ID {main_msg.message_id}")

        # ШАГ 2: отправляем 4 копируемых сообщения последовательно
        async def send_and_track(text: str):
            msg = await callback.bot.send_message(
                callback.message.chat.id,
                f"<code>{text}</code>",
            )
            track_order_file_message(callback.from_user.id, order_id, msg.message_id)

        for msg_text in copy_messages:
            await send_and_track(msg_text)
            await asyncio.sleep(PAYMENT_MESSAGE_DELAY)

        # Отправляем новое сообщение о выборе предоплаты
        payment_choice_msg = await callback.bot.send_message(
            callback.message.chat.id,
            "Вам буде зручніше передоплата 200 грн чи повна оплата?"
        )
        track_order_file_message(callback.from_user.id, order_id, payment_choice_msg.message_id)

        elapsed_time = (asyncio.get_event_loop().time() - start_time) * 1000
        debug_print(f"💳 Payment info sent successfully in {elapsed_time:.0f}ms")

        tracked = get_order_file_messages(callback.from_user.id, order_id)
        assert len(tracked) == 6
        debug_print(f"📌 Tracking all {len(tracked)} messages for order {order_id}")

    except Exception as e:
        debug_print(f"❌ Error sending payment info: {e}", "ERROR")
        await callback.answer(f"❌ Помилка відправки реквізитів", show_alert=True)


@router.callback_query(F.data.contains(":contacted"))
async def on_contacted(callback: CallbackQuery):
    """Кнопка 'Зв'язались' - С АТОМАРНЫМИ ОПЕРАЦИЯМИ"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or str(user_id)

    debug_print(f"🎯 CONTACTED: order {order_id} by user {user_id}")

    with get_session() as session:
        # АТОМАРНОЕ изменение статуса
        success, order, error_msg = change_order_status_atomic(
            session=session,
            order_id=order_id,
            expected_status=OrderStatus.NEW,
            new_status=OrderStatus.WAITING_PAYMENT,
            user_id=user_id,
            username=username
        )

        if not success:
            if order is None:
                await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            else:
                # Показываем детальную ошибку конфликта статуса
                await callback.answer(f"⚠️ {error_msg}", show_alert=True)

                # Обновляем карточку актуальными данными
                try:
                    session.refresh(order)  # Перезагружаем объект из БД
                    message_text = build_order_card_message(order, detailed=True)
                    keyboard = get_correct_keyboard(order, callback.message)

                    await callback.message.edit_text(message_text, reply_markup=keyboard)
                    debug_print(f"♻️ Updated card with current status: {order.status.value}")
                except Exception as e:
                    debug_print(f"Failed to refresh card after conflict: {e}", "WARN")

            return

        # Успешно изменили статус - обновляем карточку
        try:
            message_text = build_order_card_message(order, detailed=True)
            keyboard = get_correct_keyboard(order, callback.message)

            await callback.message.edit_text(message_text, reply_markup=keyboard)
            await callback.answer("✅ Статус: Очікує оплату")

            debug_print(f"✅ CONTACTED SUCCESS: order {order_id}")

        except Exception as e:
            debug_print(f"Failed to edit message after status change: {e}", "WARN")
            await callback.answer("✅ Статус змінено (помилка оновлення)")

    # Уведомляем других менеджеров об изменении (асинхронно)
    if success:
        try:
            await notify_other_managers_about_status_change(
                callback.bot,
                order,
                OrderStatus.NEW,
                OrderStatus.WAITING_PAYMENT,
                user_id,
                username
            )
        except Exception as e:
            debug_print(f"Failed to notify other managers: {e}", "WARN")


@router.callback_query(F.data.contains(":paid"))
async def on_paid(callback: CallbackQuery):
    """Кнопка 'Оплатили' - С АТОМАРНЫМИ ОПЕРАЦИЯМИ"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or str(user_id)

    debug_print(f"🎯 PAID: order {order_id} by user {user_id}")

    with get_session() as session:
        # АТОМАРНОЕ изменение статуса
        success, order, error_msg = change_order_status_atomic(
            session=session,
            order_id=order_id,
            expected_status=OrderStatus.WAITING_PAYMENT,
            new_status=OrderStatus.PAID,
            user_id=user_id,
            username=username
        )

        if not success:
            if order is None:
                await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            else:
                await callback.answer(f"⚠️ {error_msg}", show_alert=True)

                # Обновляем карточку актуальными данными
                try:
                    session.refresh(order)
                    message_text = build_order_card_message(order, detailed=True)
                    keyboard = get_correct_keyboard(order, callback.message)

                    await callback.message.edit_text(message_text, reply_markup=keyboard)
                except Exception as e:
                    debug_print(f"Failed to refresh card after conflict: {e}", "WARN")

            return

        # Успешно изменили статус
        try:
            message_text = build_order_card_message(order, detailed=True)
            keyboard = get_correct_keyboard(order, callback.message)

            await callback.message.edit_text(message_text, reply_markup=keyboard)
            await callback.answer("✅ Замовлення оплачено")

            debug_print(f"✅ PAID SUCCESS: order {order_id}")

        except Exception as e:
            debug_print(f"Failed to edit message after status change: {e}", "WARN")
            await callback.answer("✅ Статус змінено (помилка оновлення)")

    # Уведомляем других менеджеров
    if success:
        try:
            await notify_other_managers_about_status_change(
                callback.bot,
                order,
                OrderStatus.WAITING_PAYMENT,
                OrderStatus.PAID,
                user_id,
                username
            )
        except Exception as e:
            debug_print(f"Failed to notify other managers: {e}", "WARN")


@router.callback_query(F.data.contains(":cancel"))
async def on_cancel(callback: CallbackQuery):
    """Кнопка 'Скасування' - С АТОМАРНЫМИ ОПЕРАЦИЯМИ"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or str(user_id)

    debug_print(f"🎯 CANCEL: order {order_id} by user {user_id}")

    with get_session() as session:
        # Сначала получаем текущий заказ для определения ожидаемого статуса
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        if order.status == OrderStatus.CANCELLED:
            await callback.answer("⚠️ Замовлення вже скасовано", show_alert=True)
            return

        # Запоминаем старый статус для уведомлений
        old_status = order.status

        # АТОМАРНОЕ изменение статуса (отмена возможна из любого статуса кроме CANCELLED)
        success, updated_order, error_msg = change_order_status_atomic(
            session=session,
            order_id=order_id,
            expected_status=old_status,  # Ожидаемый = текущий
            new_status=OrderStatus.CANCELLED,
            user_id=user_id,
            username=username
        )

        if not success:
            if updated_order is None:
                await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            else:
                await callback.answer(f"⚠️ {error_msg}", show_alert=True)

                # Обновляем карточку актуальными данными
                try:
                    session.refresh(updated_order)
                    message_text = build_order_card_message(updated_order, detailed=True)
                    keyboard = get_correct_keyboard(updated_order, callback.message)

                    await callback.message.edit_text(message_text, reply_markup=keyboard)
                except Exception as e:
                    debug_print(f"Failed to refresh card after conflict: {e}", "WARN")

            return

        # Успешно отменили заказ
        try:
            message_text = build_order_card_message(updated_order, detailed=True)
            keyboard = get_correct_keyboard(updated_order, callback.message)

            await callback.message.edit_text(message_text, reply_markup=keyboard)
            await callback.answer("❌ Замовлення скасовано")

            debug_print(f"✅ CANCEL SUCCESS: order {order_id}")

        except Exception as e:
            debug_print(f"Failed to edit message after status change: {e}", "WARN")
            await callback.answer("✅ Статус змінено (помилка оновлення)")

    # Уведомляем других менеджеров
    if success:
        try:
            await notify_other_managers_about_status_change(
                callback.bot,
                updated_order,
                old_status,
                OrderStatus.CANCELLED,
                user_id,
                username
            )
        except Exception as e:
            debug_print(f"Failed to notify other managers: {e}", "WARN")