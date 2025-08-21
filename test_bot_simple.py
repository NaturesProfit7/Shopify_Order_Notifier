#!/usr/bin/env python3
"""
Простая проверка работы бота
"""

import os
import sys
from pathlib import Path

# Добавляем корень проекта в путь
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

from dotenv import load_dotenv

load_dotenv()


def test_basic_setup():
    """Проверка базовой настройки"""
    print("🧪 ПРОВЕРКА БАЗОВОЙ НАСТРОЙКИ")
    print("=" * 50)

    # Проверяем переменные
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")

    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return False

    if not chat_id:
        print("❌ TELEGRAM_TARGET_CHAT_ID не установлен")
        return False

    print(f"✅ Bot Token: {bot_token[:10]}...")
    print(f"✅ Chat ID: {chat_id}")

    # Проверяем импорты
    try:
        from app.bot.main import get_bot_instance
        print("✅ Импорт bot.main успешен")

        from app.bot.routers import management
        print("✅ Импорт management router успешен")

        from app.bot.routers.management import CommentStates
        print("✅ Импорт CommentStates успешен")

    except Exception as e:
        print(f"❌ Ошибка импорта: {e}")
        return False

    # Проверяем создание бота
    try:
        bot_instance = get_bot_instance()
        print("✅ Экземпляр бота создан")

        dp = bot_instance.dp
        print("✅ Диспетчер доступен")

        storage = dp.storage
        print(f"✅ Storage: {type(storage).__name__}")

    except Exception as e:
        print(f"❌ Ошибка создания бота: {e}")
        return False

    print("\n✅ Базовая настройка в порядке!")
    return True


def main():
    """Главная функция"""

    if not test_basic_setup():
        print("\n❌ Есть проблемы с базовой настройкой")
        return

    print(f"\n{'=' * 50}")
    print("📝 ИНСТРУКЦИИ ДЛЯ ТЕСТИРОВАНИЯ:")
    print("-" * 50)
    print("1. Перезапустите сервер:")
    print("   uvicorn app.main:app --host 0.0.0.0 --port 8003")
    print()
    print("2. В Telegram боту:")
    print("   - Отправьте /start")
    print("   - Нажмите 'Необроблені'")
    print("   - Выберите любой заказ")
    print("   - Нажмите '💬 Коментар'")
    print("   - Введите текст комментария")
    print()
    print("3. В логах ищите:")
    print("   - ✅ Management router registered (FSM)")
    print("   - 🎯 Comment button pressed by user...")
    print("   - 📝 COMMENT MESSAGE RECEIVED from user...")
    print("   - ✅ Comment processing completed successfully")
    print()
    print("4. Если бот не отвечает на /start:")
    print("   - Проверьте, что сервер запущен")
    print("   - Проверьте TELEGRAM_BOT_TOKEN")
    print("   - Проверьте логи на наличие ошибок")


if __name__ == "__main__":
    main()