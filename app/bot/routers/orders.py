# app/bot/routers/orders.py - ПОЛНОЕ ИГНОРИРОВАНИЕ НЕАВТОРИЗОВАННЫХ
"""Роутер для работы с заказами: просмотр, изменение статусов, отправка файлов"""

from datetime import datetime
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
    order_card_keyboard,
    is_webhook_order_message,
    get_webhook_order_keyboard
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


def get_correct_keyboard(order: Order, callback_message) -> any:
    """Выбирает правильную клавиатуру в зависимости от источника заказа"""
    if is_webhook_order_message(callback_message):
        debug_print(f"Using webhook keyboard for order {order.id}")
        return get_webhook_order_keyboard(order)
    else:
        debug_print(f"Using regular keyboard for order {order.id}")
        return order_card_keyboard(order)


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

    await cleanup_order_files(
        callback.bot,
        callback.message.chat.id,
        callback.from_user.id,
        order_id
    )
    debug_print(f"✅ Cleaned up files for order {order_id}")

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

                from app.services.message_templates import render_simple_confirm_with_contact
                from app.services.address_utils import get_delivery_and_contact_info, get_contact_name

                _, contact_info = get_delivery_and_contact_info(order.raw_json)
                contact_first_name, contact_last_name = get_contact_name(contact_info)

                client_message = render_simple_confirm_with_contact(
                    order.raw_json,
                    contact_first_name,
                    contact_last_name
                )

                pdf_msg = await callback.bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=pdf_file,
                    caption=client_message
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
            debug_print(f"Error sending {file_type}: {e}", "ERROR")
            await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)


@router.callback_query(F.data.contains(":payment"))
async def on_payment_info(callback: CallbackQuery):
    """Кнопка 'Реквізити' - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"💳 PAYMENT: for order {order_id}")

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

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

        await cleanup_order_files(callback.bot, callback.message.chat.id, callback.from_user.id, order_id)

        main_msg = await callback.bot.send_message(
            callback.message.chat.id,
            payment_message
        )
        track_order_file_message(callback.from_user.id, order_id, main_msg.message_id)

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
    """Кнопка 'Зв'язались' - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"🎯 CONTACTED: order {order_id}")

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

        message_text = build_order_card_message(order, detailed=True)
        keyboard = get_correct_keyboard(order, callback.message)

        try:
            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except Exception as e:
            debug_print(f"Failed to edit message: {e}", "WARN")

        await callback.answer("✅ Статус: Очікує оплату")


@router.callback_query(F.data.contains(":paid"))
async def on_paid(callback: CallbackQuery):
    """Кнопка 'Оплатили' - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"🎯 PAID: order {order_id}")

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

        message_text = build_order_card_message(order, detailed=True)
        keyboard = get_correct_keyboard(order, callback.message)

        try:
            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except Exception as e:
            debug_print(f"Failed to edit message: {e}", "WARN")

        await callback.answer("✅ Замовлення оплачено")


@router.callback_query(F.data.contains(":cancel"))
async def on_cancel(callback: CallbackQuery):
    """Кнопка 'Скасування' - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(callback.from_user.id):
        return

    order_id = int(callback.data.split(":")[1])
    debug_print(f"🎯 CANCEL: order {order_id}")

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

        message_text = build_order_card_message(order, detailed=True)
        keyboard = get_correct_keyboard(order, callback.message)

        try:
            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except Exception as e:
            debug_print(f"Failed to edit message: {e}", "WARN")

        await callback.answer("❌ Замовлення скасовано")