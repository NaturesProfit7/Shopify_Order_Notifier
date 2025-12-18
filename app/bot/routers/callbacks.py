# app/bot/routers/callbacks.py - ПОЛНАЯ ЗАМЕНА
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from typing import Dict, Set, Optional

from app.db import get_session
from app.models import Order, OrderStatus, OrderStatusHistory
from app.bot.services.message_builder import (
    get_status_emoji,
    get_status_text,
    build_order_message,
    DIVIDER,
)
from app.services.pdf_service import build_order_pdf
from app.services.vcf_service import build_contact_vcf
from app.services.menu_ui import order_card_buttons
from app.services.tg_service import send_text_with_buttons
import os

router = Router()

# Хранилище для отслеживания сообщений каждого пользователя
user_navigation_messages: Dict[int, int] = {}  # user_id -> message_id
user_order_files: Dict[int, Dict[int, Set[int]]] = {}  # user_id -> {order_id -> {message_ids}}


# FSM состояния для ввода комментария
class CommentStates(StatesGroup):
    waiting_for_comment = State()


def check_permission(user_id: int) -> bool:
    """Проверка прав доступа"""
    allowed_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    allowed = [int(uid.strip()) for uid in allowed_ids.split(",") if uid.strip()]
    return not allowed or user_id in allowed


def track_navigation_message(user_id: int, message_id: int):
    """Отслеживаем основное навигационное сообщение пользователя"""
    user_navigation_messages[user_id] = message_id


async def on_order_view_click(cb: CallbackQuery):
    """Show detailed order information when callback is received."""
    parts = (cb.data or "").split(":")
    try:
        order_id = int(parts[1])
    except (IndexError, ValueError):
        await cb.answer()
        return

    with get_session() as session:
        order = session.get(Order, order_id)

    message = build_order_message(order, detailed=True)
    buttons = order_card_buttons(order.id)
    await send_text_with_buttons(message, buttons)
    await cb.answer()


def track_order_file_message(user_id: int, order_id: int, message_id: int):
    """Отслеживаем файловые сообщения заказа"""
    if user_id not in user_order_files:
        user_order_files[user_id] = {}
    if order_id not in user_order_files[user_id]:
        user_order_files[user_id][order_id] = set()
    user_order_files[user_id][order_id].add(message_id)


async def cleanup_order_files(bot, chat_id: int, user_id: int, order_id: int):
    """Удаляем все файловые сообщения конкретного заказа"""
    if user_id in user_order_files and order_id in user_order_files[user_id]:
        for msg_id in list(user_order_files[user_id][order_id]):
            try:
                await bot.delete_message(chat_id, msg_id)
            except:
                pass
        # Очищаем отслеживание
        user_order_files[user_id][order_id].clear()


async def update_navigation_message(bot, chat_id: int, user_id: int, text: str,
                                    reply_markup: InlineKeyboardMarkup = None) -> bool:
    """Обновляем основное навигационное сообщение пользователя"""
    last_message_id = user_navigation_messages.get(user_id)

    if last_message_id:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=last_message_id,
                reply_markup=reply_markup
            )
            return True
        except (TelegramBadRequest, Exception):
            # Если не удалось отредактировать - отправим новое
            pass

    # Отправляем новое сообщение
    message = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup
    )
    track_navigation_message(user_id, message.message_id)
    return True


def format_phone_compact(e164: str) -> str:
    """Форматирует телефон компактно без пробелов"""
    if not e164:
        return "Не вказано"
    return e164


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


def get_order_card_keyboard(order: Order) -> InlineKeyboardMarkup:
    """Клавиатура для карточки заказа"""
    buttons = []

    # Кнопки статуса
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

    # Файлы
    buttons.append([
        InlineKeyboardButton(text="📄 PDF", callback_data=f"order:{order.id}:resend:pdf"),
        InlineKeyboardButton(text="📱 VCF", callback_data=f"order:{order.id}:resend:vcf")
    ])

    # Реквизиты
    buttons.append([
        InlineKeyboardButton(text="💳 Реквізити", callback_data=f"order:{order.id}:payment")
    ])

    # Дополнительные действия
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


@router.callback_query(F.data == "menu:main")
async def on_main_menu(callback: CallbackQuery):
    """Главное меню"""
    buttons = [
        [InlineKeyboardButton(text="📋 Необроблені", callback_data="orders:list:pending:offset=0")],
        [InlineKeyboardButton(text="📦 Всі замовлення", callback_data="orders:list:all:offset=0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show")]
    ]

    await update_navigation_message(
        callback.bot,
        callback.message.chat.id,
        callback.from_user.id,
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("orders:list:"))
async def on_orders_list(callback: CallbackQuery):
    """Список заказов"""
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
            await update_navigation_message(
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

            text += f"{emoji} #{order_no} • {customer}\n"

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

        await update_navigation_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            text,
            InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    await callback.answer()


@router.callback_query(F.data.regexp(r"^order:\d+:view$"))
async def on_order_view(callback: CallbackQuery):
    """Показать карточку заказа"""
    order_id = int(callback.data.split(":")[1])

    with get_session() as session:
        order = session.get(Order, order_id)
        if not order:
            await callback.answer("❌ Замовлення не знайдено", show_alert=True)
            return

        message_text = build_order_card_message(order, detailed=True)
        keyboard = get_order_card_keyboard(order)

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

    # Сначала удаляем все старые файлы этого заказа
    await cleanup_order_files(callback.bot, callback.message.chat.id, callback.from_user.id, order_id)

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
            await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)


@router.callback_query(F.data.contains(":payment"))
async def on_payment_info(callback: CallbackQuery):
    """Кнопка 'Реквізити'"""
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
            "ФОП Комарницька Катерина Сергіївна",
            "3577508940",
            "Оплата за товар"
        ]

        for msg_text in copy_messages:
            copy_msg = await callback.bot.send_message(
                callback.message.chat.id,
                f"<code>{msg_text}</code>"
            )
            track_order_file_message(callback.from_user.id, order_id, copy_msg.message_id)

        # Отправляем новое сообщение о выборе предоплаты
        payment_choice_msg = await callback.bot.send_message(
            callback.message.chat.id,
            "Вам буде зручніше передоплата 200 грн чи повна оплата?"
        )
        track_order_file_message(callback.from_user.id, order_id, payment_choice_msg.message_id)

        await callback.answer("💳 Реквізити відправлені")


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


@router.callback_query(F.data.startswith("orders:list:pending:offset=0"))
async def on_back_to_pending_list(callback: CallbackQuery):
    """Кнопка 'До списку' - возврат к списку с очисткой файлов"""

    # Если это переход из карточки заказа - очищаем все файлы пользователя
    if callback.message and callback.message.text and "Замовлення #" in callback.message.text:
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
    callback.data = "orders:list:pending:offset=0"
    await on_orders_list(callback)


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

        await update_navigation_message(
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


@router.message(F.text == "/menu")
async def on_menu_command(message: Message):
    """Команда /menu"""
    # Удаляем команду пользователя
    try:
        await message.delete()
    except:
        pass

    buttons = [
        [InlineKeyboardButton(text="📋 Необроблені", callback_data="orders:list:pending:offset=0")],
        [InlineKeyboardButton(text="📦 Всі замовлення", callback_data="orders:list:all:offset=0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show")]
    ]

    # Пытаемся обновить существующее сообщение
    await update_navigation_message(
        message.bot,
        message.chat.id,
        message.from_user.id,
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery):
    """Пустой обработчик"""
    await callback.answer()