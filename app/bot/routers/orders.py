# app/bot/routers/orders.py - ОЧИЩЕННАЯ ВЕРСИЯ
"""Роутер для работы с заказами: просмотр, изменение статусов, отправка файлов"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile

from app.db import get_session
from app.models import Order, OrderStatus, OrderStatusHistory
from app.bot.services.message_builder import get_status_emoji, get_status_text
from app.services.pdf_service import build_order_pdf
from app.services.vcf_service import build_contact_vcf

from .shared import (
    debug_print,
    check_permission,
    format_phone_compact,
    track_order_file_message,
    cleanup_order_files,
    update_navigation_message,
    order_card_keyboard
)

router = Router()


def build_order_card_message(order: Order, detailed: bool = False) -> str:
    """Построить сообщение карточки заказа"""
    order_no = order.order_number or order.id
    status_emoji = get_status_emoji(order.status)
    status_text = get_status_text(order.status)

    customer_name = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"
    phone = format_phone_compact(order.customer_phone_e164)

    message = f"""📦 <b>Замовлення #{order_no}</b> • {status_emoji} {status_text}
━━━━━━━━━━━━━━━━━━━━━━
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

    message += "\n━━━━━━━━━━━━━━━━━━━━━━"

    # Дополнительная информация
    if order.comment:
        message += f"\n💬 <i>Коментар: {order.comment}</i>"

    if order.reminder_at:
        reminder_time = order.reminder_at.strftime("%d.%m %H:%M")
        message += f"\n⏰ <i>Нагадування: {reminder_time}</i>"

    if order.processed_by_username:
        message += f"\n👨‍💼 <i>Менеджер: @{order.processed_by_username}</i>"

    return message


@router.callback_query(F.data.regexp(r"^order:\d+:view$"))
async def on_order_view(callback: CallbackQuery):
    """Показать карточку заказа"""
    order_id = int(callback.data.split(":")[1])
    debug_print(f"Order view callback: order {order_id} from user {callback.from_user.id}")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        message_text = build_order_card_message(order, detailed=True)
        keyboard = order_card_keyboard(order)

        await update_navigation_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            message_text,
            keyboard
        )

    await callback.answer()


@router.callback_query(F.data.contains(":resend:"))
async def on_resend_file(callback: CallbackQuery):
    """Повторная отправка PDF или VCF"""
    parts = callback.data.split(":")
    order_id = int(parts[1])
    file_type = parts[3]

    debug_print(f"Resend {file_type} for order {order_id} from user {callback.from_user.id}")

    # Сначала удаляем все старые файлы этого заказа
    await cleanup_order_files(callback.bot, callback.message.chat.id, callback.from_user.id, order_id)

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order or not order.raw_json:
            await callback.answer("❌ Дані замовлення не знайдено", show_alert=True)
            return

        try:
            if file_type == "pdf":
                pdf_bytes, pdf_filename = build_order_pdf(order.raw_json)
                pdf_file = BufferedInputFile(pdf_bytes, pdf_filename)

                customer_message = f"""💬 <b>Повідомлення клієнту:</b>

<i>Вітаю, {order.customer_first_name or 'клієнте'} ☺️
Ваше замовлення №{order.order_number or order.id}
Все вірно?</i>"""

                pdf_msg = await callback.bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=pdf_file,
                    caption=customer_message
                )

                track_order_file_message(callback.from_user.id, order_id, pdf_msg.message_id)
                await callback.answer("✅ PDF відправлено")

            elif file_type == "vcf":
                vcf_bytes, vcf_filename = build_contact_vcf(
                    first_name=order.customer_first_name or "",
                    last_name=order.customer_last_name or "",
                    order_id=str(order.order_number or order.id),
                    phone_e164=order.customer_phone_e164
                )
                vcf_file = BufferedInputFile(vcf_bytes, vcf_filename)

                caption = f"📱 Контакт клієнта • #{order.order_number or order.id}"
                if order.customer_phone_e164:
                    caption += f" • {format_phone_compact(order.customer_phone_e164)}"

                vcf_msg = await callback.bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=vcf_file,
                    caption=caption
                )

                track_order_file_message(callback.from_user.id, order_id, vcf_msg.message_id)
                await callback.answer("✅ VCF відправлено")

        except Exception as e:
            debug_print(f"Error sending {file_type} for order {order_id}: {e}", "ERROR")
            await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)


@router.callback_query(F.data.contains(":payment"))
async def on_payment_info(callback: CallbackQuery):
    """Кнопка 'Реквізити'"""
    order_id = int(callback.data.split(":")[1])
    debug_print(f"Payment info for order {order_id} from user {callback.from_user.id}")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Получаем сумму заказа
        order_total = "800"
        currency = "грн"

        if order.raw_json:
            total_price = order.raw_json.get("total_price")
            order_currency = order.raw_json.get("currency", "UAH")
            if total_price:
                try:
                    order_total = str(int(float(total_price)))
                    currency = "грн" if order_currency == "UAH" else order_currency
                except:
                    pass

        payment_message = f"""💳 <b>Реквізити для оплати</b>

Передаємо замовлення в роботу після предплати, так як виготовлення повністю індивідуально 

Максимальний термін виготовлення складає 7 робочих днів, одразу по готовності відправляємо замовлення Вам 🚀

🛍 <b>Сума замовлення складає - {order_total} {currency}</b>

Оплату можна здійснити на:
<b>ФОП Нитяжук Катерина Сергіївна</b>
<code>UA613220010000026004340089782</code>
<b>ЕДРПОУ:</b> 3577508940
<b>Призначення:</b> Оплата за товар 

Надсилаю всю інформацію окремо, щоб вам було зручно копіювати ☺️👇"""

        # Удаляем старые файлы этого заказа
        await cleanup_order_files(callback.bot, callback.message.chat.id, callback.from_user.id, order_id)

        # Отправляем новые сообщения
        main_msg = await callback.bot.send_message(
            callback.message.chat.id,
            payment_message
        )
        track_order_file_message(callback.from_user.id, order_id, main_msg.message_id)

        # Отправляем отдельные сообщения для копирования
        copy_messages = [
            "UA613220010000026004340089782",
            "ФОП Нитяжук Катерина Сергіївна",
            "3577508940",
            "Оплата за товар"
        ]

        for msg_text in copy_messages:
            copy_msg = await callback.bot.send_message(
                callback.message.chat.id,
                f"<code>{msg_text}</code>"
            )
            track_order_file_message(callback.from_user.id, order_id, copy_msg.message_id)

        await callback.answer("💳 Реквізити відправлені")


@router.callback_query(F.data.contains(":contacted"))
async def on_contacted(callback: CallbackQuery):
    """Кнопка 'Зв'язались'"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"Status change to WAITING_PAYMENT for order {order_id} by user {callback.from_user.id}")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        if order.status != OrderStatus.NEW:
            await callback.answer("⚠️ Статус вже змінено", show_alert=True)
            return

        old_status = order.status
        order.status = OrderStatus.WAITING_PAYMENT
        order.processed_by_user_id = callback.from_user.id
        order.processed_by_username = callback.from_user.username or callback.from_user.first_name

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
        message_text = build_order_card_message(order, detailed=True)
        keyboard = order_card_keyboard(order)

        await update_navigation_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            message_text,
            keyboard
        )

        await callback.answer("✅ Статус: Очікує оплату")

        # Уведомление в чат
        notification = f"📝 Замовлення #{order.order_number or order.id} • Статус: ⏳ Очікує оплату"
        await callback.bot.send_message(callback.message.chat.id, notification)


@router.callback_query(F.data.contains(":cancel"))
async def on_cancel(callback: CallbackQuery):
    """Кнопка 'Скасування'"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"Status change to CANCELLED for order {order_id} by user {callback.from_user.id}")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        if order.status == OrderStatus.CANCELLED:
            await callback.answer("⚠️ Замовлення вже скасовано", show_alert=True)
            return

        old_status = order.status
        order.status = OrderStatus.CANCELLED

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
        message_text = build_order_card_message(order, detailed=True)
        keyboard = order_card_keyboard(order)

        await update_navigation_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            message_text,
            keyboard
        )

        await callback.answer("❌ Замовлення скасовано")

        # Уведомление
        notification = f"❌ Замовлення #{order.order_number or order.id} скасовано"
        await callback.bot.send_message(callback.message.chat.id, notification)


@router.callback_query(F.data.contains(":paid"))
async def on_paid(callback: CallbackQuery):
    """Кнопка 'Оплатили'"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"Status change to PAID for order {order_id} by user {callback.from_user.id}")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        if order.status != OrderStatus.WAITING_PAYMENT:
            await callback.answer("⚠️ Неможливо змінити статус", show_alert=True)
            return

        old_status = order.status
        order.status = OrderStatus.PAID

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
        message_text = build_order_card_message(order, detailed=True)
        keyboard = order_card_keyboard(order)

        await update_navigation_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            message_text,
            keyboard
        )

        await callback.answer("✅ Замовлення оплачено")

        # Уведомление
        notification = f"💰 Замовлення #{order.order_number or order.id} оплачено!"
        await callback.bot.send_message(callback.message.chat.id, notification)


@router.callback_query(F.data.startswith("orders:list:pending:offset=0"))
async def on_back_to_pending_list(callback: CallbackQuery):
    """Кнопка 'До списку' - возврат к списку с очисткой файлов"""
    debug_print(f"Back to pending list from user {callback.from_user.id}")

    # Если это переход из карточки заказа - очищаем все файлы пользователя
    if callback.message and callback.message.text and "Замовлення #" in callback.message.text:
        from .shared.state import user_order_files
        # Очищаем все файлы пользователя
        if callback.from_user.id in user_order_files:
            for order_id in list(user_order_files[callback.from_user.id].keys()):
                await cleanup_order_files(
                    callback.bot,
                    callback.message.chat.id,
                    callback.from_user.id,
                    order_id
                )

    # Показываем список
    from .navigation import on_orders_list
    callback.data = "orders:list:pending:offset=0"
    await on_orders_list(callback)