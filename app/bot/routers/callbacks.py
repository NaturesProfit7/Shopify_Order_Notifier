# app/bot/routers/callbacks.py
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.db import get_session
from app.models import Order, OrderStatus, OrderStatusHistory
from app.bot.services.message_builder import get_status_emoji, get_status_text
from app.services.pdf_service import build_order_pdf
from app.services.vcf_service import build_contact_vcf
from app.services.phone_utils import normalize_ua_phone
import os

router = Router()


# FSM состояния для ввода комментария
class CommentStates(StatesGroup):
    waiting_for_comment = State()


def check_permission(user_id: int) -> bool:
    """Проверка прав доступа"""
    allowed_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    allowed = [int(uid.strip()) for uid in allowed_ids.split(",") if uid.strip()]
    return not allowed or user_id in allowed  # Если список пустой - доступ всем


def format_phone_compact(e164: str) -> str:
    """Форматирует телефон компактно без пробелов: +380960790247"""
    if not e164:
        return "Не вказано"
    # Просто возвращаем E.164 без изменений
    return e164


def build_order_card_message(order: Order, detailed: bool = False) -> str:
    """Построить сообщение карточки заказа в едином формате"""
    order_no = order.order_number or order.id
    status_emoji = get_status_emoji(order.status)
    status_text = get_status_text(order.status)

    # Имя клиента
    customer_name = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"

    # Телефон БЕЗ пробелов
    phone = format_phone_compact(order.customer_phone_e164)

    # Основное сообщение
    message = f"""📦 <b>Замовлення #{order_no}</b> • {status_emoji} {status_text}
━━━━━━━━━━━━━━━━━━━━━━
👤 {customer_name}
📱 {phone}"""

    # Если есть данные о товарах (из raw_json)
    if detailed and order.raw_json:
        data = order.raw_json

        # Товары
        items = data.get("line_items", [])
        if items:
            items_text = []
            total_sum = 0
            for item in items[:5]:  # Показываем первые 5
                title = item.get("title", "")
                qty = item.get("quantity", 0)
                price = float(item.get("price", 0))
                total_sum += price * qty
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

    # Комментарий, если есть
    if order.comment:
        message += f"\n💬 <i>Коментар: {order.comment}</i>"

    # Напоминание, если установлено
    if order.reminder_at:
        reminder_time = order.reminder_at.strftime("%d.%m %H:%M")
        message += f"\n⏰ <i>Нагадування: {reminder_time}</i>"

    # Информация о менеджере
    if order.processed_by_username:
        message += f"\n👨‍💼 <i>Менеджер: @{order.processed_by_username}</i>"

    return message


def get_order_card_keyboard(order: Order) -> InlineKeyboardMarkup:
    """Клавиатура для карточки заказа"""
    buttons = []

    # Кнопки изменения статуса
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

    # Дополнительные действия для активных заказов
    if order.status in [OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]:
        buttons.append([
            InlineKeyboardButton(text="💬 Коментар", callback_data=f"order:{order.id}:comment"),
            InlineKeyboardButton(text="⏰ Нагадати", callback_data=f"order:{order.id}:reminder")
        ])

    # Кнопки для файлов (без "Оновити")
    buttons.append([
        InlineKeyboardButton(text="📄 PDF", callback_data=f"order:{order.id}:resend:pdf"),
        InlineKeyboardButton(text="📱 VCF", callback_data=f"order:{order.id}:resend:vcf")
    ])

    # Навигация
    buttons.append([
        InlineKeyboardButton(text="↩️ До списку", callback_data=f"orders:list:pending:offset=0")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.regexp(r"^order:\d+:view$"))
async def on_order_view(callback: CallbackQuery):
    """Показать полную карточку заказа"""
    order_id = int(callback.data.split(":")[1])

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Используем единый формат
        message_text = build_order_card_message(order, detailed=True)
        keyboard = get_order_card_keyboard(order)

        try:
            await callback.message.edit_text(
                message_text,
                reply_markup=keyboard
            )
        except Exception:
            await callback.message.answer(
                message_text,
                reply_markup=keyboard
            )

    await callback.answer()


@router.callback_query(F.data == "menu:main")
async def on_main_menu(callback: CallbackQuery):
    """Главное меню - ЕДИНСТВЕННАЯ версия"""
    buttons = [
        [InlineKeyboardButton(text="📋 Необроблені", callback_data="orders:list:pending:offset=0")],
        [InlineKeyboardButton(text="📦 Всі замовлення", callback_data="orders:list:all:offset=0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show")]
    ]

    await callback.message.edit_text(
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("orders:list:"))
async def on_orders_list(callback: CallbackQuery):
    """Список заказов с пагинацией"""
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("❌ Некоректні дані", show_alert=True)
        return

    kind = parts[2]
    try:
        offset = int(parts[3].replace("offset=", ""))
    except:
        offset = 0

    PAGE_SIZE = 5

    with get_session() as session:
        query = session.query(Order)

        if kind == "pending":
            query = query.filter(Order.status.in_([OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]))

        total = query.count()
        orders = query.order_by(Order.created_at.desc()).offset(offset).limit(PAGE_SIZE).all()

        if not orders:
            buttons = [[
                InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu:main")
            ]]
            await callback.message.edit_text(
                "📭 Немає замовлень для відображення",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            await callback.answer()
            return

        # Заголовок
        if kind == "pending":
            text = "📋 <b>Необроблені замовлення:</b>\n\n"
        else:
            text = "📦 <b>Всі замовлення:</b>\n\n"

        # Кнопки для каждого заказа
        buttons = []
        for order in orders:
            order_no = order.order_number or order.id
            customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"
            emoji = get_status_emoji(order.status)

            # Текст в списке
            text += f"{emoji} №{order_no} • {customer}\n"

            # Кнопка
            button_text = f"№{order_no} • {customer[:20]}"
            buttons.append([
                InlineKeyboardButton(text=button_text, callback_data=f"order:{order.id}:view")
            ])

        # Пагинация
        nav_buttons = []
        if offset > 0:
            nav_buttons.append(
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"orders:list:{kind}:offset={offset - PAGE_SIZE}")
            )

        current_page = (offset // PAGE_SIZE) + 1
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        nav_buttons.append(
            InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="noop")
        )

        if offset + PAGE_SIZE < total:
            nav_buttons.append(
                InlineKeyboardButton(text="Вперед ➡️", callback_data=f"orders:list:{kind}:offset={offset + PAGE_SIZE}")
            )

        if nav_buttons:
            buttons.append(nav_buttons)

        # Главное меню
        buttons.append([
            InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu:main")
        ])

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    await callback.answer()


@router.callback_query(F.data.contains(":contacted"))
async def on_contacted(callback: CallbackQuery):
    """Кнопка 'Зв'язались'"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])

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
        keyboard = get_order_card_keyboard(order)

        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard
        )

        await callback.answer("✅ Статус: Очікує оплату")

        # Уведомление в чат
        notification = f"📝 Замовлення №{order.order_number or order.id} • Статус: ⏳ Очікує оплату"
        await callback.bot.send_message(callback.message.chat.id, notification)


@router.callback_query(F.data.contains(":cancel"))
async def on_cancel(callback: CallbackQuery):
    """Кнопка 'Скасування'"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])

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
        keyboard = get_order_card_keyboard(order)

        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard
        )

        await callback.answer("❌ Замовлення скасовано")

        # Уведомление
        notification = f"❌ Замовлення №{order.order_number or order.id} скасовано"
        await callback.bot.send_message(callback.message.chat.id, notification)


@router.callback_query(F.data.contains(":paid"))
async def on_paid(callback: CallbackQuery):
    """Кнопка 'Оплатили'"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])

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
        keyboard = get_order_card_keyboard(order)

        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard
        )

        await callback.answer("✅ Замовлення оплачено")

        # Уведомление
        notification = f"💰 Замовлення №{order.order_number or order.id} оплачено!"
        await callback.bot.send_message(callback.message.chat.id, notification)


@router.callback_query(F.data.contains(":resend:"))
async def on_resend_file(callback: CallbackQuery):
    """Повторная отправка PDF или VCF"""
    parts = callback.data.split(":")
    order_id = int(parts[1])
    file_type = parts[3]

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order or not order.raw_json:
            await callback.answer("❌ Дані замовлення не знайдено", show_alert=True)
            return

        try:
            from aiogram.types import BufferedInputFile

            if file_type == "pdf":
                pdf_bytes, pdf_filename = build_order_pdf(order.raw_json)
                pdf_file = BufferedInputFile(pdf_bytes, pdf_filename)

                caption = f"📦 Замовлення #{order.order_number or order.id}"
                if order.customer_first_name or order.customer_last_name:
                    caption += f" • {order.customer_first_name or ''} {order.customer_last_name or ''}".strip()

                await callback.bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=pdf_file,
                    caption=caption
                )
                await callback.answer("✅ PDF відправлено")

            elif file_type == "vcf":
                vcf_bytes, vcf_filename = build_contact_vcf(
                    first_name=order.customer_first_name or "",
                    last_name=order.customer_last_name or "",
                    order_id=str(order.order_number or order.id),
                    phone_e164=order.customer_phone_e164
                )
                vcf_file = BufferedInputFile(vcf_bytes, vcf_filename)

                caption = "📱 Контакт клієнта"
                if order.customer_phone_e164:
                    caption += f" • {format_phone_compact(order.customer_phone_e164)}"

                await callback.bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=vcf_file,
                    caption=caption
                )
                await callback.answer("✅ VCF відправлено")

        except Exception as e:
            await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)


@router.callback_query(F.data == "stats:show")
async def on_stats_show(callback: CallbackQuery):
    """Показать статистику"""
    with get_session() as session:
        total = session.query(Order).count()
        new = session.query(Order).filter(Order.status == OrderStatus.NEW).count()
        waiting = session.query(Order).filter(Order.status == OrderStatus.WAITING_PAYMENT).count()
        paid = session.query(Order).filter(Order.status == OrderStatus.PAID).count()
        cancelled = session.query(Order).filter(Order.status == OrderStatus.CANCELLED).count()

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = session.query(Order).filter(Order.created_at >= today).count()

        stats_text = f"""📊 <b>Статистика замовлень:</b>

📦 Всього: {total}
📅 Сьогодні: {today_count}

<b>За статусами:</b>
🆕 Нових: {new}
⏳ Очікують оплату: {waiting}
✅ Оплачених: {paid}
❌ Скасованих: {cancelled}

<i>Оновлено: {datetime.now().strftime('%H:%M')}</i>"""

        buttons = [[
            InlineKeyboardButton(text="🔄 Оновити", callback_data="stats:show"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main")
        ]]

        await callback.message.edit_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    await callback.answer("📊 Статистика оновлена")


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery):
    """Пустой обработчик для информационных кнопок"""
    await callback.answer()

# TODO: Добавить обработчики для comment и reminder (из handlers/callbacks.py)