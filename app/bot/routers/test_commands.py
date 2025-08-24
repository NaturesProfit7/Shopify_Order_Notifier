# app/bot/routers/test_commands.py - ПОЛНОЕ ИГНОРИРОВАНИЕ НЕАВТОРИЗОВАННЫХ
"""Тестовые команды для проверки уведомлений"""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from .shared import debug_print, check_permission

router = Router()


@router.message(Command("test_hourly"))
async def test_hourly_reminder(message: Message):
    """Тестовая команда для проверки ежечасного напоминания - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(message.from_user.id):
        return

    debug_print(f"Manual hourly reminder test by authorized user {message.from_user.id}")

    try:
        # Удаляем команду пользователя
        await message.delete()
    except:
        pass

    try:
        # Получаем экземпляр бота и временно отключаем проверку времени
        from app.bot.main import get_bot_instance
        bot_instance = get_bot_instance()

        # Временно переопределяем метод проверки времени
        original_method = bot_instance._is_working_hours
        bot_instance._is_working_hours = lambda: True

        await bot_instance._check_new_orders()

        # Восстанавливаем оригинальный метод
        bot_instance._is_working_hours = original_method

        # Отправляем подтверждение менеджерам без использования chat_id
        await bot_instance._send_to_managers(
            "✅ Тест ежегодного напоминания выполнен (игнорирование времени)",
            None,
        )

    except Exception as e:
        debug_print(f"Error in hourly test: {e}", "ERROR")
        await message.answer(f"❌ Помилка тесту: {str(e)}")


@router.message(Command("test_daily"))
async def test_daily_reminder(message: Message):
    """Тестовая команда для проверки ежедневного напоминания - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(message.from_user.id):
        return

    debug_print(f"Manual daily reminder test by authorized user {message.from_user.id}")

    try:
        # Удаляем команду пользователя
        await message.delete()
    except:
        pass

    try:
        # Получаем экземпляр бота и вызываем проверку
        from app.bot.main import get_bot_instance
        bot_instance = get_bot_instance()

        await bot_instance._check_payment_reminders()

        # Отправляем подтверждение менеджерам
        await bot_instance._send_to_managers(
            "✅ Тест ежедневного напоминания выполнен",
            None,
        )

    except Exception as e:
        debug_print(f"Error in daily test: {e}", "ERROR")
        await message.answer(f"❌ Помилка тесту: {str(e)}")


@router.message(Command("test_reminder"))
async def test_individual_reminder(message: Message):
    """Тестовая команда для проверки индивидуальных напоминаний - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(message.from_user.id):
        return

    debug_print(f"Manual individual reminder test by authorized user {message.from_user.id}")

    try:
        # Удаляем команду пользователя
        await message.delete()
    except:
        pass

    try:
        # Получаем экземпляр бота и вызываем проверку
        from app.bot.main import get_bot_instance
        bot_instance = get_bot_instance()

        await bot_instance._check_reminders()

        # Отправляем подтверждение менеджерам
        await bot_instance._send_to_managers(
            "✅ Тест індивідуальних нагадувань виконан",
            None,
        )

    except Exception as e:
        debug_print(f"Error in reminder test: {e}", "ERROR")
        await message.answer(f"❌ Помилка тесту: {str(e)}")


@router.message(Command("test_time"))
async def test_working_hours(message: Message):
    """Тестовая команда для проверки рабочего времени - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(message.from_user.id):
        return

    try:
        # Удаляем команду пользователя
        await message.delete()
    except:
        pass

    try:
        # Получаем экземпляр бота и проверяем время
        from app.bot.main import get_bot_instance
        from datetime import datetime
        import pytz

        bot_instance = get_bot_instance()
        is_working = bot_instance._is_working_hours()

        kiev_tz = pytz.timezone("Europe/Kyiv")
        now_kiev = datetime.now(kiev_tz)

        status = "✅ Робочий час" if is_working else "❌ Не робочий час"
        time_str = now_kiev.strftime("%H:%M")

        info = await message.answer(
            f"🕐 <b>Поточний час:</b> {time_str} (Київ)\n"
            f"📅 <b>Статус:</b> {status}\n"
            f"⏰ <b>Робочі години:</b> 10:00 - 22:00"
        )

        # Удаляем через 5 секунд
        import asyncio
        await asyncio.sleep(5)
        try:
            await info.delete()
        except:
            pass

    except Exception as e:
        debug_print(f"Error in time test: {e}", "ERROR")
        await message.answer(f"❌ Помилка тесту: {str(e)}")


@router.message(Command("get_order"))
async def get_order_json(message: Message):
    """Получить JSON заказа - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(message.from_user.id):
        return

    try:
        # Удаляем команду пользователя
        await message.delete()
    except:
        pass

    try:
        parts = message.text.split()
        if len(parts) != 2:
            error_msg = await message.answer("Використання: /get_order ORDER_ID")
            import asyncio
            await asyncio.sleep(5)
            try:
                await error_msg.delete()
            except:
                pass
            return

        order_id = int(parts[1])
        debug_print(f"Getting JSON for order {order_id} by authorized user {message.from_user.id}")

        from app.services.shopify_service import get_order
        order_data = get_order(order_id)

        # Сохраняем в файл
        import json
        filename = f"order_{order_id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(order_data, f, indent=2, ensure_ascii=False)

        # Проверяем адреса для информации
        shipping = order_data.get("shipping_address", {})
        billing = order_data.get("billing_address", {})

        info_text = f"JSON заказа #{order_id} сохранен в {filename}\n\n"

        if shipping and billing:
            ship_addr = f"{shipping.get('address1', '')} {shipping.get('city', '')}".strip()
            bill_addr = f"{billing.get('address1', '')} {billing.get('city', '')}".strip()

            if ship_addr != bill_addr:
                info_text += "📦 Разные адреса обнаружены:\n"
                info_text += f"Shipping: {ship_addr}\n"
                info_text += f"Billing: {bill_addr}"
            else:
                info_text += "📍 Адреса одинаковые"

        result_msg = await message.answer(info_text)

        # Удаляем через 10 секунд
        import asyncio
        await asyncio.sleep(10)
        try:
            await result_msg.delete()
        except:
            pass

    except ValueError:
        error_msg = await message.answer("❌ Некорректний ID заказа")
        import asyncio
        await asyncio.sleep(3)
        try:
            await error_msg.delete()
        except:
            pass
    except Exception as e:
        debug_print(f"Error getting order JSON: {e}", "ERROR")
        error_msg = await message.answer(f"❌ Помилка: {str(e)}")
        import asyncio
        await asyncio.sleep(5)
        try:
            await error_msg.delete()
        except:
            pass


@router.message(Command("test_help"))
async def test_help(message: Message):
    """Справка по тестовым командам - ПОЛНОЕ ИГНОРИРОВАНИЕ неавторизованных"""
    if not check_permission(message.from_user.id):
        return

    try:
        # Удаляем команду пользователя
        await message.delete()
    except:
        pass

    help_text = """🧪 <b>Тестові команди для нагадувань:</b>

<b>Перевірка уведомлень:</b>
/test_hourly - тест ежегодного напоминания (NEW заказы)
/test_daily - тест ежедневного напоминания (WAITING заказы)  
/test_reminder - тест индивидуальных напоминаний

<b>Утиліти:</b>
/test_time - перевірка робочого часу
/get_order ORDER_ID - отримати JSON заказа
/test_help - ця довідка

<b>Примітка:</b>
• Команди доступні тільки менеджерам
• Повідомлення видаляються автоматично
• Логи тестів дивіться в консолі сервера"""

    help_msg = await message.answer(help_text)

    # Удаляем через 10 секунд
    import asyncio
    await asyncio.sleep(10)
    try:
        await help_msg.delete()
    except:
        pass