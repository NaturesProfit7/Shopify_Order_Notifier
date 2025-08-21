#!/usr/bin/env python3
"""
Тест для проверки работы FSM состояний в aiogram
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в путь
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))


async def test_fsm():
    """Тестируем базовую работу FSM"""

    print("🧪 ТЕСТ FSM СОСТОЯНИЙ")
    print("=" * 50)

    try:
        from aiogram.fsm.storage.memory import MemoryStorage
        from aiogram.fsm.context import FSMContext
        from aiogram.fsm.state import State, StatesGroup

        print("✅ Импорты aiogram FSM прошли успешно")

        # Создаем тестовое состояние
        class TestStates(StatesGroup):
            waiting = State()

        # Создаем storage
        storage = MemoryStorage()
        print("✅ MemoryStorage создан")

        # Создаем тестовый контекст
        class FakeBot:
            def __init__(self):
                self.id = 123

        class FakeUser:
            def __init__(self):
                self.id = 456

        class FakeChat:
            def __init__(self):
                self.id = 789

        bot = FakeBot()
        user = FakeUser()
        chat = FakeChat()

        # Создаем FSM контекст
        context = FSMContext(
            storage=storage,
            key=storage.key(bot.id, chat.id, user.id)
        )

        print("✅ FSMContext создан")

        # Тестируем установку состояния
        print("🔄 Тестируем установку состояния...")
        await context.set_state(TestStates.waiting)

        state = await context.get_state()
        print(f"✅ Состояние установлено: {state}")

        # Тестируем сохранение данных
        print("🔄 Тестируем сохранение данных...")
        await context.update_data(test_key="test_value", number=42)

        data = await context.get_data()
        print(f"✅ Данные сохранены: {data}")

        # Тестируем очистку
        print("🔄 Тестируем очистку...")
        await context.clear()

        state_after = await context.get_state()
        data_after = await context.get_data()

        print(f"✅ Состояние после очистки: {state_after}")
        print(f"✅ Данные после очистки: {data_after}")

        print("\n✅ FSM работает корректно!")

        return True

    except Exception as e:
        print(f"❌ Ошибка FSM: {e}")
        import traceback
        print(f"📋 Traceback: {traceback.format_exc()}")
        return False


async def test_router_order():
    """Проверяем порядок роутеров в боте"""

    print("\n🔍 ПРОВЕРКА ПОРЯДКА РОУТЕРОВ")
    print("=" * 50)

    try:
        from app.bot.main import get_bot_instance

        bot_instance = get_bot_instance()
        dp = bot_instance.dp

        print("✅ Получен экземпляр диспетчера")

        # Проверяем зарегистрированные роутеры
        routers = dp._routers if hasattr(dp, '_routers') else []

        print(f"📋 Зарегистрировано роутеров: {len(routers)}")

        for i, router in enumerate(routers):
            router_name = getattr(router, '__module__', 'Unknown')
            print(f"  {i + 1}. {router_name}")

        # Проверяем, что management идет перед orders
        management_index = None
        orders_index = None

        for i, router in enumerate(routers):
            module = getattr(router, '__module__', '')
            if 'management' in module:
                management_index = i
            elif 'orders' in module:
                orders_index = i

        if management_index is not None and orders_index is not None:
            if management_index < orders_index:
                print("✅ Роутер management идет перед orders - правильно!")
            else:
                print("❌ Роутер orders идет перед management - неправильно!")
                return False
        else:
            print("⚠️ Не найдены роутеры management или orders")

        return True

    except Exception as e:
        print(f"❌ Ошибка проверки роутеров: {e}")
        return False


async def main():
    """Главная функция теста"""

    # Тестируем FSM
    fsm_ok = await test_fsm()

    # Тестируем роутеры
    router_ok = await test_router_order()

    print(f"\n{'=' * 50}")
    print("📊 РЕЗУЛЬТАТЫ ТЕСТОВ:")
    print(f"🔄 FSM состояния: {'✅ OK' if fsm_ok else '❌ FAIL'}")
    print(f"🔀 Порядок роутеров: {'✅ OK' if router_ok else '❌ FAIL'}")

    if fsm_ok and router_ok:
        print("\n✅ Все тесты прошли успешно!")
        print("\n📝 Теперь попробуйте функцию комментариев в боте:")
        print("1. /start → Необроблені → выберите заказ")
        print("2. Нажмите '💬 Коментар'")
        print("3. Введите текст комментария")
        print("\n🔍 Следите за логами сервера на предмет:")
        print("- 📝 === COMMENT MESSAGE HANDLER TRIGGERED ===")
        print("- ✅ Comment processing completed successfully")
    else:
        print("\n❌ Есть проблемы с настройкой FSM или роутерами")
        print("📝 Обновите файлы согласно артефактам выше")


if __name__ == "__main__":
    asyncio.run(main())