# app/bot/routers/commands.py - ИСПРАВЛЕННЫЕ КОМАНДЫ БЕЗ ЦИКЛИЧЕСКИХ ИМПОРТОВ
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.db import get_session
from app.models import Order, OrderStatus
from datetime import datetime

from .shared import (
    debug_print,
    check_permission,
    track_navigation_message,
    update_navigation_message,
)

router = Router()


def main_menu_keyboard():
    """Главное меню - ЛОКАЛЬНАЯ ВЕРСИЯ БЕЗ ИМПОРТА"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = [
        [InlineKeyboardButton(text="📋 Необроблені", callback_data="orders:list:new:offset=0")],
        [InlineKeyboardButton(text="💳 Очікують оплати", callback_data="orders:list:waiting:offset=0")],
        [InlineKeyboardButton(text="📦 Всі замовлення", callback_data="orders:list:all:offset=0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats:show")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def stats_keyboard():
    """Клавиатура статистики - ЛОКАЛЬНАЯ ВЕРСИЯ"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = [[
        InlineKeyboardButton(text="🔄 Оновити", callback_data="stats:refresh"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main")
    ]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_menu_keyboard():
    """Кнопка возврата в главное меню - ЛОКАЛЬНАЯ ВЕРСИЯ"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    buttons = [[
        InlineKeyboardButton(text="🏠 Головне меню", callback_data="menu:main")
    ]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
    """Команда /start - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    # ПРОВЕРКА ПРАВ - ПОЛНОЕ ИГНОРИРОВАНИЕ
    if not check_permission(msg.from_user.id):
        # НЕ отвечаем вообще - полное игнорирование
        return

    debug_print(f"/start command from authorized user {msg.from_user.id}")

    # Удаляем команду пользователя
    try:
        await msg.delete()
    except:
        pass

    # Пытаемся обновить существующее меню, если есть
    success = await update_navigation_message(
        msg.bot,
        msg.chat.id,
        msg.from_user.id,
        "🤖 <b>Бот активний!</b>\n\n"
        "Керуйте замовленнями через кнопки нижче.\n"
        "Використовуйте /menu для повернення до головного меню.",
        None
    )

    # Если обновить не удалось - отправляем приветствие
    if not success:
        await msg.answer(
            "🤖 <b>Бот активний!</b>\n\n"
            "Керуйте замовленнями через кнопки нижче.\n"
            "Використовуйте /menu для повернення до головного меню."
        )

    # Отправляем/обновляем главное меню
    await update_navigation_message(
        msg.bot,
        msg.chat.id,
        msg.from_user.id,
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        main_menu_keyboard()
    )


@router.message(Command(commands=["menu"]))
async def on_menu_command(msg: Message):
    """Команда /menu - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    # ПРОВЕРКА ПРАВ - ПОЛНОЕ ИГНОРИРОВАНИЕ
    if not check_permission(msg.from_user.id):
        return

    debug_print(f"/menu command from authorized user {msg.from_user.id}")

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
    """Команда /stats - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    # ПРОВЕРКА ПРАВ - ПОЛНОЕ ИГНОРИРОВАНИЕ
    if not check_permission(msg.from_user.id):
        return

    debug_print(f"/stats command from authorized user {msg.from_user.id}")

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
    """Команда /pending - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    # ПРОВЕРКА ПРАВ - ПОЛНОЕ ИГНОРИРОВАНИЕ
    if not check_permission(msg.from_user.id):
        return

    debug_print(f"/pending command from authorized user {msg.from_user.id}")

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
            # Импортируем обработчик из navigation БЕЗ ЦИКЛИЧЕСКИХ ИМПОРТОВ
            try:
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

            except ImportError as e:
                debug_print(f"Could not import navigation router: {e}", "WARN")
                # Fallback - просто показываем меню
                await update_navigation_message(
                    msg.bot,
                    msg.chat.id,
                    msg.from_user.id,
                    "🏠 <b>Головне меню</b>\n\nВикористовуйте кнопки для навігації:",
                    main_menu_keyboard()
                )

    except Exception as e:
        debug_print(f"Error switching to pending: {e}", "ERROR")


@router.message(Command(commands=["help"]))
async def on_help_command(msg: Message):
    """Команда /help - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    # ПРОВЕРКА ПРАВ - ПОЛНОЕ ИГНОРИРОВАНИЕ
    if not check_permission(msg.from_user.id):
        return

    debug_print(f"/help command from authorized user {msg.from_user.id}")

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
    """Обработчик любых других сообщений - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    # ПРОВЕРКА ПРАВ - ПОЛНОЕ ИГНОРИРОВАНИЕ
    if not check_permission(msg.from_user.id):
        return

    debug_print(f"Any message from authorized user {msg.from_user.id}: {msg.text}")

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