# app/bot/routers/commands.py - РЕФАКТОРИНГ
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.db import get_session
from app.models import Order, OrderStatus
from datetime import datetime

from .shared import (
    debug_print,
    track_navigation_message,
    update_navigation_message,
    main_menu_keyboard,
    stats_keyboard,
    back_to_menu_keyboard
)

router = Router()


async def send_main_menu(bot, chat_id: int, user_id: int) -> None:
    """Отправляем главное меню и отслеживаем его"""
    message = await bot.send_message(
        chat_id=chat_id,
        text="🏠 <b>Головне меню</b>\n\nОберіть дію:",
        reply_markup=main_menu_keyboard()
    )

    # Отслеживаем это сообщение для последующего редактирования
    track_navigation_message(user_id, message.message_id)


@router.message(CommandStart())
async def on_start(msg: Message):
    """Команда /start"""
    debug_print(f"/start command from user {msg.from_user.id}")

    # Удаляем команду пользователя
    try:
        await msg.delete()
    except:
        pass

    # Отправляем приветствие
    await msg.answer(
        "🤖 <b>Бот активний!</b>\n\n"
        "Керуйте замовленнями через кнопки нижче.\n"
        "Використовуйте /menu для повернення до головного меню."
    )

    # Отправляем главное меню и отслеживаем его
    await send_main_menu(msg.bot, msg.chat.id, msg.from_user.id)


@router.message(Command(commands=["menu"]))
async def on_menu_command(msg: Message):
    """Команда /menu"""
    debug_print(f"/menu command from user {msg.from_user.id}")

    # Удаляем команду пользователя
    try:
        await msg.delete()
    except Exception as e:
        debug_print(f"Failed to delete /menu command: {e}", "WARN")

    # Пытаемся обновить существующее сообщение
    success = await update_navigation_message(
        msg.bot,
        msg.chat.id,
        msg.from_user.id,
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        main_menu_keyboard()
    )

    debug_print(f"/menu update success: {success}")


@router.message(Command(commands=["stats"]))
async def on_stats_command(msg: Message):
    """Команда /stats - показать статистику"""
    debug_print(f"/stats command from user {msg.from_user.id}")

    # Удаляем команду пользователя
    try:
        await msg.delete()
    except:
        pass

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

        message = await msg.answer(
            stats_text,
            reply_markup=stats_keyboard()
        )

        # Отслеживаем это сообщение
        track_navigation_message(msg.from_user.id, message.message_id)


@router.message(Command(commands=["pending"]))
async def on_pending_command(msg: Message):
    """Команда /pending - показать необработанные заказы"""
    debug_print(f"/pending command from user {msg.from_user.id}")

    # Удаляем команду пользователя
    try:
        await msg.delete()
    except:
        pass

    # Отправляем главное меню, потом переключимся на pending
    await send_main_menu(msg.bot, msg.chat.id, msg.from_user.id)

    # Через короткую паузу переключаемся на pending список
    import asyncio
    await asyncio.sleep(0.3)

    try:
        # Имитируем нажатие кнопки "Необроблені"
        success = await update_navigation_message(
            msg.bot,
            msg.chat.id,
            msg.from_user.id,
            "🔄 Завантаження необроблених замовлень...",
            None
        )

        if success:
            # Импортируем обработчик из navigation
            from .navigation import on_orders_list

            # Создаем фиктивный callback
            class FakeCallback:
                def __init__(self):
                    self.data = "orders:list:pending:offset=0"
                    self.from_user = msg.from_user
                    self.bot = msg.bot
                    self.message = type('obj', (object,), {'chat': msg.chat})()

                async def answer(self, text=None, show_alert=False):
                    pass

            fake_callback = FakeCallback()
            await on_orders_list(fake_callback)

    except Exception as e:
        debug_print(f"Error switching to pending: {e}", "ERROR")


@router.message(Command(commands=["help"]))
async def on_help_command(msg: Message):
    """Команда /help - показать справку"""
    debug_print(f"/help command from user {msg.from_user.id}")

    # Удаляем команду пользователя
    try:
        await msg.delete()
    except:
        pass

    help_text = """📖 <b>Довідка по боту:</b>

<b>Команди:</b>
/menu - Головне меню
/stats - Статистика замовлень
/pending - Необроблені замовлення
/help - Ця довідка

<b>Функції:</b>
• Перегляд списків замовлень
• Зміна статусів замовлень
• Відправка PDF та VCF файлів
• Додавання коментарів
• Встановлення нагадувань
• Відправка реквізитів для оплати

<b>Статуси замовлень:</b>
🆕 Новий - щойно створений заказ
⏳ Очікує оплату - зв'язались з клієнтом
✅ Оплачено - заказ оплачений
❌ Скасовано - заказ скасований

Використовуйте кнопки для навігації та управління замовленнями."""

    message = await msg.answer(
        help_text,
        reply_markup=back_to_menu_keyboard()
    )

    # Отслеживаем это сообщение
    track_navigation_message(msg.from_user.id, message.message_id)


# Обработчик для всех остальных текстовых сообщений
@router.message()
async def on_any_message(msg: Message):
    """Обработчик любых других сообщений"""
    # Удаляем сообщение пользователя (если это не команда)
    if not msg.text or not msg.text.startswith('/'):
        try:
            await msg.delete()
        except:
            pass

        # Отправляем краткое напоминание
        reminder = await msg.answer(
            "💬 Використовуйте /menu для управління замовленнями",
            reply_markup=back_to_menu_keyboard()
        )

        # Удаляем напоминание через 5 секунд
        import asyncio
        await asyncio.sleep(5)
        try:
            await reminder.delete()
        except:
            pass