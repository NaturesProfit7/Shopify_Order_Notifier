# app/bot/routers/navigation.py - ЧИСТЫЕ ПЕРЕХОДЫ ИЗ УВЕДОМЛЕНИЙ
"""Роутер для навигации: главное меню, списки заказов, статистика"""

from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton

from app.db import get_session
from app.models import Order, OrderStatus
from app.bot.services.message_builder import get_status_emoji

from .shared import (
    debug_print,
    update_navigation_message,
    track_navigation_message,
    cleanup_all_navigation,
    main_menu_keyboard,
    stats_keyboard,
    orders_list_keyboard,
    back_to_menu_keyboard
)

router = Router()


def _is_from_notification(callback: CallbackQuery) -> bool:
    """
    Проверяем, был ли переход из уведомления.
    Уведомления содержат специфический текст и кнопки.
    """
    if not callback.message or not callback.message.text:
        return False

    message_text = callback.message.text

    # Проверяем характерные признаки уведомлений
    notification_indicators = [
        "Необроблені замовлення (",  # из hourly reminder
        "Очікують оплату (",  # из daily reminder
        "🚀 Час перетворити",  # фраза из NEW уведомлений
        "⚡ Час закривати",  # фраза из WAITING уведомлений
    ]

    return any(indicator in message_text for indicator in notification_indicators)


@router.callback_query(F.data == "menu:main")
async def on_main_menu(callback: CallbackQuery):
    """Главное меню"""
    debug_print(f"Main menu callback from user {callback.from_user.id}")

    await update_navigation_message(
        callback.bot,
        callback.message.chat.id,
        callback.from_user.id,
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        main_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^orders:list:(new|pending|all|waiting):offset=\d+$"))
async def on_orders_list(callback: CallbackQuery):
    """Список заказов - с поддержкой чистых переходов из уведомлений"""
    debug_print(f"Orders list callback: {callback.data} from user {callback.from_user.id}")

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
    debug_print(f"Processing orders list: kind={kind}, offset={offset}")

    # КЛЮЧЕВАЯ ЛОГИКА: Проверяем, переходим ли мы из уведомления
    is_from_notification = _is_from_notification(callback)
    debug_print(f"Is from notification: {is_from_notification}")

    with get_session() as session:
        query = session.query(Order)

        if kind == "new":
            query = query.filter(Order.status == OrderStatus.NEW)
        elif kind == "pending":
            query = query.filter(Order.status.in_([OrderStatus.NEW, OrderStatus.WAITING_PAYMENT]))
        elif kind == "waiting":
            query = query.filter(Order.status == OrderStatus.WAITING_PAYMENT)
        # для "all" фильтр не нужен

        query = query.order_by(
            Order.order_number.desc().nullslast(),
            Order.id.desc()
        )

        total = query.count()
        orders = query.offset(offset).limit(PAGE_SIZE).all()

        if not orders:
            text = "📭 Немає замовлень для відображення"
            keyboard = back_to_menu_keyboard()
        else:
            # Заголовок
            if kind == "new":
                text = "📋 <b>Необроблені замовлення (NEW):</b>\n\n"
            elif kind == "pending":
                text = "📋 <b>Необроблені замовлення:</b>\n\n"
            elif kind == "waiting":
                text = "💳 <b>Очікують оплату:</b>\n\n"
            else:
                text = "📦 <b>Всі замовлення:</b>\n\n"

            # Кнопки для каждого заказа
            order_buttons = []
            for order in orders:
                order_no = order.order_number or order.id
                customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"
                emoji = get_status_emoji(order.status)

                text += f"{emoji} #{order_no} • {customer}\n"

                button_text = f"{emoji} #{order_no} • {customer[:20]}"
                order_buttons.append([
                    InlineKeyboardButton(text=button_text, callback_data=f"order:{order.id}:view")
                ])

            # Создаем полную клавиатуру
            keyboard = orders_list_keyboard(kind, offset, PAGE_SIZE, total, has_orders=True)

            # Добавляем кнопки заказов в начало
            full_keyboard = order_buttons + keyboard.inline_keyboard

            from aiogram.types import InlineKeyboardMarkup
            keyboard = InlineKeyboardMarkup(inline_keyboard=full_keyboard)

        # ЧИСТЫЙ ПЕРЕХОД ИЗ УВЕДОМЛЕНИЯ
        if is_from_notification:
            debug_print(f"🧹 Clean transition from notification - clearing all navigation")

            # 1. Удаляем ВСЕ старые навигационные сообщения
            await cleanup_all_navigation(callback.bot, callback.message.chat.id, callback.from_user.id)

            # 2. Отправляем новое сообщение в чистый чат
            new_message = await callback.bot.send_message(
                callback.message.chat.id,
                text,
                reply_markup=keyboard
            )

            # 3. Отслеживаем новое сообщение
            track_navigation_message(callback.from_user.id, new_message.message_id)

            debug_print(f"✅ Clean transition completed - new message: {new_message.message_id}")

        else:
            # Обычное обновление существующего сообщения
            debug_print(f"Regular navigation update")
            await update_navigation_message(
                callback.bot,
                callback.message.chat.id,
                callback.from_user.id,
                text,
                keyboard
            )

    await callback.answer()


@router.callback_query(F.data == "stats:show")
async def on_stats_show(callback: CallbackQuery):
    """Показать статистику"""
    debug_print(f"Stats callback from user {callback.from_user.id}")

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

        await update_navigation_message(
            callback.bot,
            callback.message.chat.id,
            callback.from_user.id,
            stats_text,
            stats_keyboard()
        )

    await callback.answer("📊 Статистика оновлена")


@router.callback_query(F.data == "stats:refresh")
async def on_stats_refresh(callback: CallbackQuery):
    """Обновить статистику"""
    debug_print(f"Stats refresh from user {callback.from_user.id}")
    callback.data = "stats:show"
    await on_stats_show(callback)


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery):
    """Пустой обработчик для информационных кнопок"""
    await callback.answer()