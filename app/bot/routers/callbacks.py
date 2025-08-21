# app/bot/routers/callbacks.py - ПОЛНАЯ ЗАМЕНА
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

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
            InlineKeyboardButton(text="❌ Сорвався", callback_data=f"order:{order.id}:cancel")
        ])
    elif order.status == OrderStatus.WAITING_PAYMENT:
        buttons.append([
            InlineKeyboardButton(text="💰 Оплатили", callback_data=f"order:{order.id}:paid"),
            InlineKeyboardButton(text="❌ Сорвався", callback_data=f"order:{order.id}:cancel")
        ])

    # Кнопки для файлов и реквизитов
    buttons.append([
        InlineKeyboardButton(text="📄 PDF", callback_data=f"order:{order.id}:resend:pdf"),
        InlineKeyboardButton(text="📱 VCF", callback_data=f"order:{order.id}:resend:vcf"),
        InlineKeyboardButton(text="💳 Реквізити", callback_data=f"order:{order.id}:payment")
    ])

    # Дополнительные действия для активных заказов
    if order.status in [OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]:
        buttons.append([
            InlineKeyboardButton(text="💬 Коментар", callback_data=f"order:{order.id}:comment"),
            InlineKeyboardButton(text="⏰ Нагадати", callback_data=f"order:{order.id}:reminder")
        ])

    # Навигация
    buttons.append([
        InlineKeyboardButton(text="↩️ До списку", callback_data=f"orders:list:pending:offset=0")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_reminder_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Клавиатура выбора времени напоминания"""
    buttons = [
        [
            InlineKeyboardButton(text="15 хв", callback_data=f"reminder:{order_id}:15"),
            InlineKeyboardButton(text="30 хв", callback_data=f"reminder:{order_id}:30"),
            InlineKeyboardButton(text="1 год", callback_data=f"reminder:{order_id}:60")
        ],
        [
            InlineKeyboardButton(text="2 год", callback_data=f"reminder:{order_id}:120"),
            InlineKeyboardButton(text="4 год", callback_data=f"reminder:{order_id}:240"),
            InlineKeyboardButton(text="Завтра", callback_data=f"reminder:{order_id}:1440")
        ],
        [
            InlineKeyboardButton(text="↩️ Назад", callback_data=f"order:{order_id}:back")
        ]
    ]

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
        except TelegramBadRequest:
            # Если сообщение не изменилось, просто отвечаем на callback
            pass
        except Exception:
            await callback.message.answer(
                message_text,
                reply_markup=keyboard
            )

    await callback.answer()


@router.callback_query(F.data == "menu:main")
async def on_main_menu(callback: CallbackQuery):
    """Главное меню"""
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
    """Список заказов с пагинацией и сортировкой"""
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

        # СОРТИРОВКА: сначала по order_number (если есть), потом по id - ОТ БОЛЬШИХ К МЕНЬШИМ
        query = query.order_by(
            Order.order_number.desc().nullslast(),  # Сначала с номерами (большие первые)
            Order.id.desc()  # Потом по ID (большие первые)
        )

        total = query.count()
        orders = query.offset(offset).limit(PAGE_SIZE).all()

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
            text += f"{emoji} #{order_no} • {customer}\n"

            # Кнопка с эмодзи статуса
            button_text = f"{emoji} #{order_no} • {customer[:20]}"
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


@router.callback_query(F.data.contains(":payment"))
async def on_payment_info(callback: CallbackQuery):
    """Кнопка 'Реквізити' - отправка реквизитов для оплаты"""
    order_id = int(callback.data.split(":")[1])

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Получаем сумму заказа
        order_total = "800"  # Значение по умолчанию
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

        # Основное сообщение с реквизитами
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

        # Отправляем основное сообщение
        await callback.bot.send_message(
            callback.message.chat.id,
            payment_message
        )

        # Отправляем отдельные сообщения для копирования
        copy_messages = [
            "UA613220010000026004340089782",
            "ФОП Нитяжук Катерина Сергіївна",
            "3577508940",
            "Оплата за товар"
        ]

        for msg in copy_messages:
            await callback.bot.send_message(
                callback.message.chat.id,
                f"<code>{msg}</code>"
            )

        await callback.answer("💳 Реквізити відправлені")

        # Логируем отправку реквизитов
        history = OrderStatusHistory(
            order_id=order_id,
            old_status=order.status.value,
            new_status=order.status.value,
            changed_by_user_id=callback.from_user.id,
            changed_by_username=callback.from_user.username or callback.from_user.first_name,
            comment="Відправлені реквізити для оплати"
        )
        session.add(history)
        session.commit()


@router.callback_query(F.data.contains(":payment"))
async def on_payment_info(callback: CallbackQuery):
    """Кнопка 'Реквізити' - отправка реквизитов для оплаты"""
    order_id = int(callback.data.split(":")[1])

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Получаем сумму заказа
        order_total = "800"  # Значение по умолчанию
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

        # Основное сообщение с реквизитами
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

        # Отправляем основное сообщение
        await callback.bot.send_message(
            callback.message.chat.id,
            payment_message
        )

        # Отправляем отдельные сообщения для копирования
        copy_messages = [
            "UA613220010000026004340089782",
            "ФОП Нитяжук Катерина Сергіївна",
            "3577508940",
            "Оплата за товар"
        ]

        for msg in copy_messages:
            await callback.bot.send_message(
                callback.message.chat.id,
                f"<code>{msg}</code>"
            )

        await callback.answer("💳 Реквізити відправлені")

        # Логируем отправку реквизитов
        history = OrderStatusHistory(
            order_id=order_id,
            old_status=order.status.value,
            new_status=order.status.value,
            changed_by_user_id=callback.from_user.id,
            changed_by_username=callback.from_user.username or callback.from_user.first_name,
            comment="Відправлені реквізити для оплати"
        )
        session.add(history)
        session.commit()


@router.callback_query(F.data.contains(":comment"))
async def on_comment_button(callback: CallbackQuery, state: FSMContext):
    """Кнопка 'Коментар' - запуск FSM для ввода комментария"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])

    # Запускаем FSM для ввода комментария
    await state.set_state(CommentStates.waiting_for_comment)
    await state.update_data(order_id=order_id, message_id=callback.message.message_id)

    await callback.answer("💬 Відправте коментар до замовлення")
    await callback.bot.send_message(
        callback.message.chat.id,
        f"💬 Введіть коментар до замовлення #{order_id}:",
        reply_to_message_id=callback.message.message_id
    )


@router.message(CommentStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext):
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
        new_text = build_order_card_message(order, detailed=True)
        keyboard = get_order_card_keyboard(order)

        try:
            await message.bot.edit_message_text(
                new_text,
                chat_id=message.chat.id,
                message_id=original_message_id,
                reply_markup=keyboard
            )
        except:
            pass  # Сообщение могло быть уже изменено

        await message.reply(f"✅ Коментар додано до замовлення #{order.order_number or order.id}")

    await state.clear()


@router.callback_query(F.data.contains(":reminder"))
async def on_reminder_button(callback: CallbackQuery):
    """Кнопка 'Нагадати' - показать выбор времени"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])

    # Показываем кнопки выбора времени
    keyboard = get_reminder_keyboard(order_id)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer("⏰ Оберіть час нагадування")


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
        message_text = build_order_card_message(order, detailed=True)
        keyboard = get_order_card_keyboard(order)
        await callback.message.edit_text(message_text, reply_markup=keyboard)

        if minutes < 60:
            time_text = f"{minutes} хвилин"
        elif minutes < 1440:
            time_text = f"{minutes // 60} годин"
        else:
            time_text = "завтра"

        await callback.answer(f"✅ Нагадування встановлено через {time_text}")


@router.callback_query(F.data.contains(":back"))
async def on_back_to_order(callback: CallbackQuery):
    """Кнопка 'Назад' к карточке заказа"""
    order_id = int(callback.data.split(":")[1])

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Возвращаем карточку заказа
        message_text = build_order_card_message(order, detailed=True)
        keyboard = get_order_card_keyboard(order)
        await callback.message.edit_text(message_text, reply_markup=keyboard)

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
        notification = f"📝 Замовлення #{order.order_number or order.id} • Статус: ⏳ Очікує оплату"
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
            await callback.answer("⚠️ Замовлення вже сорвалося", show_alert=True)
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

        await callback.answer("❌ Замовлення сорвалося")

        # Уведомление
        notification = f"❌ Замовлення #{order.order_number or order.id} сорвалося"
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
        notification = f"💰 Замовлення #{order.order_number or order.id} оплачено!"
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

        current_time = datetime.now().strftime('%H:%M')

        stats_text = f"""📊 <b>Статистика замовлень:</b>

📦 Всього: {total}
📅 Сьогодні: {today_count}

<b>За статусами:</b>
🆕 Нових: {new}
⏳ Очікують оплату: {waiting}
✅ Оплачених: {paid}
❌ Скасованих: {cancelled}

<i>Оновлено: {current_time}</i>"""

        buttons = [[
            InlineKeyboardButton(text="🔄 Оновити", callback_data="stats:refresh"),
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main")
        ]]

        try:
            await callback.message.edit_text(
                stats_text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        except TelegramBadRequest:
            # Если сообщение не изменилось, просто обновляем клавиатуру
            await callback.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )

    await callback.answer("📊 Статистика оновлена")


@router.callback_query(F.data == "stats:refresh")
async def on_stats_refresh(callback: CallbackQuery):
    """Обновить статистику (отдельный обработчик для избежания ошибки)"""
    # Просто вызываем показ статистики заново
    callback.data = "stats:show"
    await on_stats_show(callback)


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery):
    """Пустой обработчик для информационных кнопок"""
    await callback.answer()