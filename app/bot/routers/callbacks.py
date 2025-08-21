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

# Хранилище ID последних сообщений для каждого пользователя
# В продакшене можно перенести в Redis или БД
user_last_messages = {}


# FSM состояния для ввода комментария
class CommentStates(StatesGroup):
    waiting_for_comment = State()


def check_permission(user_id: int) -> bool:
    """Проверка прав доступа"""
    allowed_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    allowed = [int(uid.strip()) for uid in allowed_ids.split(",") if uid.strip()]
    return not allowed or user_id in allowed  # Если список пустой - доступ всем


def store_user_message(user_id: int, message_id: int):
    """Сохраняем ID сообщения пользователя для редактирования"""
    user_last_messages[user_id] = message_id


async def edit_or_send_message(bot, chat_id: int, user_id: int, text: str,
                               reply_markup: InlineKeyboardMarkup = None):
    """Редактируем последнее сообщение пользователя или отправляем новое"""
    last_message_id = user_last_messages.get(user_id)

    if last_message_id:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=last_message_id,
                reply_markup=reply_markup
            )
            return last_message_id
        except (TelegramBadRequest, Exception):
            # Если не удалось отредактировать, отправляем новое
            pass

    # Отправляем новое сообщение
    message = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup
    )
    store_user_message(user_id, message.message_id)
    return message.message_id


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
            for item in items[:5]:  # Показываем первые 5
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
    """Клавиатура для карточки заказа - ЕДИНЫЙ ФОРМАТ"""
    buttons = []

    # Первый ряд: Кнопки статуса
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

    # Второй ряд: PDF и VCF
    buttons.append([
        InlineKeyboardButton(text="📄 PDF", callback_data=f"order:{order.id}:resend:pdf"),
        InlineKeyboardButton(text="📱 VCF", callback_data=f"order:{order.id}:resend:vcf")
    ])

    # Третий ряд: Реквизиты (на всю ширину)
    buttons.append([
        InlineKeyboardButton(text="💳 Реквізити", callback_data=f"order:{order.id}:payment")
    ])

    # Четвертый ряд: Дополнительные действия (для активных заказов)
    if order.status in [OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]:
        buttons.append([
            InlineKeyboardButton(text="💬 Коментар", callback_data=f"order:{order.id}:comment"),
            InlineKeyboardButton(text="⏰ Нагадати", callback_data=f"order:{order.id}:reminder")
        ])

    # Пятый ряд: Навигация
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


@router.callback_query(F.data == "menu:main")
async def on_main_menu(callback: CallbackQuery):
    """Главное меню - РЕДАКТИРУЕМ сообщение"""
    buttons = [
        [InlineKeyboardButton(text="📋 Необроблені", callback_data="orders:list:pending:offset=0")],
        [InlineKeyboardButton(text="📦 Всі замовлення", callback_data="orders:list:all:offset=0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show")]
    ]

    await edit_or_send_message(
        callback.bot,
        callback.message.chat.id,
        callback.from_user.id,
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("orders:list:"))
async def on_orders_list(callback: CallbackQuery):
    """Список заказов - РЕДАКТИРУЕМ сообщение"""
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
            Order.order_number.desc().nullslast(),
            Order.id.desc()
        )

        total = query.count()
        orders = query.offset(offset).limit(PAGE_SIZE).all()

        if not orders:
            buttons = [[
                InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu:main")
            ]]
            await edit_or_send_message(
                callback.bot,
                callback.message.chat.id,
                callback.from_user.id,
                "📭 Немає замовлень для відображення",
                InlineKeyboardMarkup(inline_keyboard=buttons)
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

        await edit_or_send_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            text,
            InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    await callback.answer()


@router.callback_query(F.data.regexp(r"^order:\d+:view$"))
async def on_order_view(callback: CallbackQuery):
    """Показать карточку заказа - РЕДАКТИРУЕМ сообщение"""
    order_id = int(callback.data.split(":")[1])

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        # Используем единый формат
        message_text = build_order_card_message(order, detailed=True)
        keyboard = get_order_card_keyboard(order)

        await edit_or_send_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            message_text,
            keyboard
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
        main_msg = await callback.bot.send_message(
            callback.message.chat.id,
            payment_message
        )

        # Отслеживаем основное сообщение с реквизитами
        track_order_message(callback.from_user.id, order_id, main_msg.message_id)

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
            # Отслеживаем каждое сообщение с реквизитами
            track_order_message(callback.from_user.id, order_id, copy_msg.message_id)

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
    await state.update_data(order_id=order_id, original_message_id=callback.message.message_id)

    # Отправляем запрос комментария БЕЗ reply
    prompt_msg = await callback.bot.send_message(
        callback.message.chat.id,
        f"💬 Введіть коментар до замовлення #{order_id}:"
    )

    # Сохраняем ID сообщения с запросом для последующего удаления
    await state.update_data(prompt_message_id=prompt_msg.message_id)

    await callback.answer("💬 Очікую ваш коментар")


@router.message(CommentStates.waiting_for_comment)
async def process_comment(message: Message, state: FSMContext):
    """Обработка введенного комментария"""
    if not check_permission(message.from_user.id):
        await message.reply("❌ У вас немає прав для цієї дії")
        await state.clear()
        return

    data = await state.get_data()
    order_id = data.get("order_id")
    original_message_id = data.get("original_message_id")
    prompt_message_id = data.get("prompt_message_id")

    comment_text = message.text

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await message.reply("❌ Замовлення не знайдено")
            await state.clear()
            return

        # Сохраняем комментарий
        order.comment = comment_text

        # Добавляем в историю
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

        # Обновляем исходное сообщение с заказом
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
            pass

        # Отправляем уведомление в новом формате
        notification = f'✅ Коментар "{comment_text}" додано до замовлення #{order.order_number or order.id}'
        await message.bot.send_message(message.chat.id, notification)

        # Удаляем вспомогательные сообщения
        try:
            # Удаляем сообщение с запросом комментария
            if prompt_message_id:
                await message.bot.delete_message(message.chat.id, prompt_message_id)

            # Удаляем сообщение пользователя с комментарием
            await message.bot.delete_message(message.chat.id, message.message_id)
        except:
            pass

    await state.clear()


@router.callback_query(F.data.contains(":reminder"))
async def on_reminder_button(callback: CallbackQuery):
    """Кнопка 'Нагадати' - показать выбор времени"""
    if not check_permission(callback.from_user.id):
        await callback.answer("❌ У вас немає прав для цієї дії", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])

    # Показываем кнопки выбора времени - РЕДАКТИРУЕМ сообщение
    keyboard = get_reminder_keyboard(order_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer("⏰ Оберіть час нагадування")
    except:
        await callback.answer("⏰ Оберіть час нагадування", show_alert=True)


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

        try:
            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except:
            pass

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

        try:
            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except:
            pass

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

        try:
            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except:
            pass

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

        try:
            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except:
            pass

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

        try:
            await callback.message.edit_text(message_text, reply_markup=keyboard)
        except:
            pass

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

                # PDF с caption для клиента
                customer_message = f"""💬 <b>Повідомлення клієнту:</b>

<i>Вітаю, {order.customer_first_name or 'клієнте'} ☺️
Ваше замовлення №{order.order_number or order.id}
Все вірно?</i>"""

                pdf_msg = await callback.bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=pdf_file,
                    caption=customer_message
                )

                # Отслеживаем PDF сообщение
                track_order_message(callback.from_user.id, order_id, pdf_msg.message_id)
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

                # Отслеживаем VCF сообщение
                track_order_message(callback.from_user.id, order_id, vcf_msg.message_id)
                await callback.answer("✅ VCF відправлено")

        except Exception as e:
            await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)


@router.callback_query(F.data == "stats:show")
async def on_stats_show(callback: CallbackQuery):
    """Показать статистику - РЕДАКТИРУЕМ сообщение"""
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

        await edit_or_send_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            stats_text,
            InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    await callback.answer("📊 Статистика оновлена")


@router.callback_query(F.data == "stats:refresh")
async def on_stats_refresh(callback: CallbackQuery):
    """Обновить статистику"""
    callback.data = "stats:show"
    await on_stats_show(callback)


# Добавим новый обработчик для кнопки "До списку"
@router.callback_query(F.data.startswith("orders:list:pending:offset=0"))
async def on_back_to_pending_list(callback: CallbackQuery):
    """Кнопка 'До списку' - возврат к списку необработанных с очисткой"""

    # Если переход из карточки заказа - удаляем связанные сообщения
    if callback.message and callback.message.text and "Замовлення #" in callback.message.text:
        # Извлекаем order_id из текста сообщения
        try:
            import re
            match = re.search(r'Замовлення #(\d+)', callback.message.text)
            if match:
                order_number = match.group(1)
                # Найдем order_id по номеру
                with get_session() as session:
                    order = session.query(Order).filter(
                        (Order.order_number == order_number) | (Order.id == int(order_number))
                    ).first()

                    if order:
                        # Удаляем все связанные сообщения
                        await delete_order_related_messages(
                            callback.bot,
                            callback.message.chat.id,
                            callback.from_user.id,
                            order.id,
                            str(order.order_number or order.id)
                        )
        except Exception as e:
            # Если не смогли извлечь - продолжаем без удаления
            pass

    # Показываем список необработанных (используем существующий обработчик)
    callback.data = "orders:list:pending:offset=0"
    await on_orders_list(callback)


# Добавим обработчик команды /menu
@router.message(F.text == "/menu")
async def on_menu_command(message: Message):
    """Команда /menu - показать главное меню с редактированием"""
    buttons = [
        [InlineKeyboardButton(text="📋 Необроблені", callback_data="orders:list:pending:offset=0")],
        [InlineKeyboardButton(text="📦 Всі замовлення", callback_data="orders:list:all:offset=0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show")]
    ]

    new_message = await message.answer(
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

    # Сохраняем ID нового сообщения для последующего редактирования
    store_user_message(message.from_user.id, new_message.message_id)


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery):
    """Пустой обработчик для информационных кнопок"""
    await callback.answer()