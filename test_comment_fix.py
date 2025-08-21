#!/usr/bin/env python3
"""
Тест для проверки функции комментариев в боте.
Запустите после перезапуска сервера.
"""

import asyncio
import os
import sys
from pathlib import Path

# Добавляем корень проекта в путь
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

from dotenv import load_dotenv

load_dotenv()


async def test_comment_functionality():
    """Тестируем функционал комментариев"""

    print("🧪 ТЕСТ ФУНКЦИИ КОММЕНТАРИЕВ")
    print("=" * 50)

    # 1. Проверяем наличие необходимых переменных
    print("1️⃣ Проверка переменных окружения...")

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")
    allowed_users = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")

    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return False

    if not chat_id:
        print("❌ TELEGRAM_TARGET_CHAT_ID не установлен")
        return False

    if not allowed_users:
        print("⚠️ TELEGRAM_ALLOWED_USER_IDS не установлен - доступ для всех")
    else:
        print(f"✅ Разрешенные пользователи: {allowed_users}")

    print(f"✅ Bot Token: {bot_token[:10]}...")
    print(f"✅ Chat ID: {chat_id}")

    # 2. Проверяем подключение к БД
    print("\n2️⃣ Проверка подключения к базе данных...")

    try:
        from app.db import get_session
        from app.models import Order

        with get_session() as session:
            count = session.query(Order).count()
            print(f"✅ Подключение к БД: найдено {count} заказов")

            # Найдем любой заказ для теста
            test_order = session.query(Order).first()
            if test_order:
                print(f"✅ Тестовый заказ: #{test_order.order_number or test_order.id}")
                return test_order.id
            else:
                print("⚠️ Нет заказов для тестирования")
                return None

    except Exception as e:
        print(f"❌ Ошибка БД: {e}")
        return False


async def main():
    """Главная функция теста"""

    # Проверяем функционал
    test_order_id = await test_comment_functionality()

    if not test_order_id:
        print("\n❌ Тест не прошел - нет данных для тестирования")
        return

    print(f"\n3️⃣ Инструкции для ручного тестирования:")
    print("-" * 50)
    print("1. Запустите бота: uvicorn app.main:app --host 0.0.0.0 --port 8003")
    print("2. Отправьте /start в Telegram боту")
    print("3. Нажмите 'Необроблені' → выберите любой заказ")
    print("4. Нажмите кнопку '💬 Коментар'")
    print("5. Введите любой текст комментария")
    print("6. Проверьте, что:")
    print("   - Комментарий добавился в карточку заказа")
    print("   - Показалось уведомление об успехе")
    print("   - Временные сообщения удалились")

    print(f"\n🎯 Для отладки используйте заказ ID: {test_order_id}")

    print("\n4️⃣ Логи для поиска проблем:")
    print("-" * 50)
    print("Ищите в логах сервера строки:")
    print("🎯 Comment button pressed by user...")
    print("📝 Comment request for order...")
    print("✅ Comment setup completed successfully")
    print("📝 Received comment message from user...")
    print("✅ Comment processing completed successfully")

    print("\n5️⃣ Возможные проблемы:")
    print("-" * 50)
    print("❌ Если видите 'Duration 5000+ ms' - проблема с FSM")
    print("❌ Если нет логов '🎯 Comment button' - роутер не срабатывает")
    print("❌ Если FSM не работает - проверьте MemoryStorage в bot/main.py")

    print("\n✅ Тест настройки завершен!")


if __name__ == "__main__":
    asyncio.run(main())