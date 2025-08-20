#!/usr/bin/env python
"""
Универсальный скрипт для тестирования обработки заказов из Shopify.

Использование:
    python test_order.py 6417067999535
    python test_order.py 6417067999535 --force
    python test_order.py 6417067999535 --details
    python test_order.py 6417067999535 --host http://example.com:8001
"""
import argparse
import base64
import hashlib
import hmac
import json
import requests
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

# Добавляем корень проекта в путь Python
root_dir = Path(__file__).resolve().parent
if root_dir.name == 'app':
    root_dir = root_dir.parent
sys.path.insert(0, str(root_dir))

import os
from dotenv import load_dotenv

load_dotenv(root_dir / '.env')


class OrderTester:
    """Класс для тестирования обработки заказов."""

    def __init__(self, host: str = "http://localhost:8001"):
        self.host = host.rstrip('/')
        self.webhook_url = f"{self.host}/webhooks/shopify/orders"
        self.secret = os.getenv("SHOPIFY_WEBHOOK_SECRET", "test_secret")

    def get_order_from_shopify(self, order_id: int) -> Optional[Dict[Any, Any]]:
        """Получает заказ из Shopify API."""
        print(f"📥 Получаем заказ #{order_id} из Shopify...")

        try:
            from app.services.shopify_service import get_order
            order_data = get_order(order_id)

            customer = order_data.get('customer', {})
            name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()

            print(f"✅ Заказ получен:")
            print(f"   • Номер: {order_data.get('name', order_data.get('order_number'))}")
            print(f"   • Клиент: {name or 'Не указан'}")
            print(f"   • Сумма: {order_data.get('total_price')} {order_data.get('currency', 'UAH')}")

            return order_data

        except Exception as e:
            print(f"❌ Ошибка получения заказа: {e}")
            return None

    def check_if_processed(self, order_id: int) -> bool:
        """Проверяет, был ли заказ уже обработан."""
        try:
            from app.db import get_session
            from app.models import Order

            with get_session() as session:
                order = session.query(Order).filter(Order.id == order_id).first()
                return order is not None and order.is_processed
        except Exception as e:
            print(f"⚠️ Не могу проверить БД: {e}")
            return False

    def reset_order(self, order_id: int) -> bool:
        """Сбрасывает флаг обработки заказа."""
        try:
            from app.db import get_session
            from app.models import Order

            with get_session() as session:
                order = session.query(Order).filter(Order.id == order_id).first()
                if order:
                    order.is_processed = False
                    session.commit()
                    print(f"🔄 Флаг обработки сброшен для заказа #{order_id}")
                    return True
                else:
                    print(f"ℹ️ Заказ #{order_id} не найден в БД (будет создан при обработке)")
                    return True
        except Exception as e:
            print(f"❌ Ошибка сброса флага: {e}")
            return False

    def send_webhook(self, order_data: Dict[Any, Any]) -> bool:
        """Отправляет webhook на сервер."""
        # Создаем HMAC подпись
        body = json.dumps(order_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        digest = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("utf-8")

        print(f"\n📤 Отправляем webhook на {self.webhook_url}")

        try:
            response = requests.post(
                self.webhook_url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Shopify-Hmac-Sha256": signature,
                },
                timeout=60  # Увеличенный таймаут для обработки
            )

            print(f"\n📨 Ответ сервера:")
            print(f"   • Статус: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                print(f"   • Результат: {result}")

                if result.get("status") == "duplicate":
                    print("\n⚠️ Заказ уже был обработан ранее")
                    print("   Используйте флаг --force для повторной обработки")
                    return False
                else:
                    print("\n✅ Заказ успешно обработан!")
                    print("   📱 Проверьте Telegram - должно прийти 3 сообщения:")
                    print("      1. PDF с деталями заказа")
                    print("      2. VCF контакт клиента")
                    print("      3. Текст для подтверждения")
                    return True
            else:
                print(f"   • Ошибка: {response.text}")
                return False

        except requests.exceptions.ConnectionError:
            print("\n❌ Не могу подключиться к серверу!")
            print(f"   Проверьте, что сервер запущен на {self.host}")
            print("\n   Для запуска сервера выполните:")
            print("   uvicorn app.main:app --host 0.0.0.0 --port 8001")
            return False

        except requests.exceptions.Timeout:
            print("\n⏱️ Таймаут при обработке заказа")
            print("   Возможно, заказ все еще обрабатывается")
            print("   Проверьте Telegram через несколько секунд")
            return False

        except Exception as e:
            print(f"\n❌ Ошибка отправки: {e}")
            return False

    def show_order_details(self, order_data: Dict[Any, Any]):
        """Показывает детальную информацию о заказе."""
        print("\n" + "=" * 50)
        print("📋 ДЕТАЛИ ЗАКАЗА")
        print("=" * 50)

        # Основная информация
        print(f"\n🏷️ Основное:")
        print(f"   • ID: {order_data.get('id')}")
        print(f"   • Номер: {order_data.get('order_number')}")
        print(f"   • Название: {order_data.get('name')}")
        print(f"   • Дата: {order_data.get('created_at')}")

        # Клиент
        customer = order_data.get('customer', {})
        if customer:
            print(f"\n👤 Клиент:")
            print(f"   • Имя: {customer.get('first_name')} {customer.get('last_name')}")
            print(f"   • Телефон: {customer.get('phone', 'Не указан')}")
            print(f"   • Email: {customer.get('email', 'Не указан')}")

        # Доставка
        shipping = order_data.get('shipping_address', {})
        if shipping:
            print(f"\n📦 Доставка:")
            print(f"   • Получатель: {shipping.get('first_name')} {shipping.get('last_name')}")
            print(f"   • Адрес: {shipping.get('address1')}")
            if shipping.get('address2'):
                print(f"   • Адрес 2: {shipping.get('address2')}")
            print(f"   • Город: {shipping.get('city')}")
            print(f"   • Индекс: {shipping.get('zip')}")
            print(f"   • Страна: {shipping.get('country')}")
            print(f"   • Телефон: {shipping.get('phone', 'Не указан')}")

        # Товары
        items = order_data.get('line_items', [])
        if items:
            print(f"\n🛍️ Товары ({len(items)} шт.):")
            for i, item in enumerate(items, 1):
                print(f"   {i}. {item.get('title')}")
                print(f"      • Количество: {item.get('quantity')}")
                print(f"      • Цена: {item.get('price')} {order_data.get('currency', 'UAH')}")

                # Свойства товара
                props = item.get('properties', [])
                if props:
                    print(f"      • Свойства:")
                    for prop in props:
                        if not str(prop.get('name', '')).startswith('_'):
                            print(f"        - {prop.get('name')}: {prop.get('value')}")

        # Итого
        print(f"\n💰 Итого:")
        print(f"   • Сумма: {order_data.get('total_price')} {order_data.get('currency', 'UAH')}")

        print("\n" + "=" * 50)

    def test_order(self, order_id: int, force: bool = False, show_details: bool = False):
        """Основной метод тестирования заказа."""
        print("=" * 50)
        print(f"🧪 ТЕСТИРОВАНИЕ ЗАКАЗА #{order_id}")
        print("=" * 50)

        # 1. Получаем заказ из Shopify
        order_data = self.get_order_from_shopify(order_id)
        if not order_data:
            return False

        # 2. Показываем детали, если запрошено
        if show_details:
            self.show_order_details(order_data)

        # 3. Проверяем, был ли уже обработан
        if not force:
            if self.check_if_processed(order_id):
                print(f"\n⚠️ Заказ #{order_id} уже был обработан")
                print("   Используйте флаг --force для повторной обработки")
                response = input("\n   Сбросить флаг и обработать заново? (y/n): ")
                if response.lower() != 'y':
                    print("   Отменено")
                    return False
                force = True

        # 4. Сбрасываем флаг, если нужно
        if force:
            if not self.reset_order(order_id):
                return False
            time.sleep(0.5)  # Небольшая пауза для БД

        # 5. Отправляем webhook
        return self.send_webhook(order_data)


def main():
    """Главная функция."""
    parser = argparse.ArgumentParser(
        description="Тестирование обработки заказов Shopify",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python test_order.py 6417067999535
  python test_order.py 6417067999535 --force
  python test_order.py 6417067999535 --details
  python test_order.py 6417067999535 --host http://production.com:8001
        """
    )

    parser.add_argument(
        "order_id",
        type=int,
        help="ID заказа из Shopify"
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Принудительно обработать заказ, даже если он уже был обработан"
    )

    parser.add_argument(
        "--details", "-d",
        action="store_true",
        help="Показать детальную информацию о заказе"
    )

    parser.add_argument(
        "--host",
        default="http://localhost:8001",
        help="Адрес сервера (по умолчанию: http://localhost:8001)"
    )

    args = parser.parse_args()

    # Создаем тестер и запускаем
    tester = OrderTester(host=args.host)
    success = tester.test_order(
        order_id=args.order_id,
        force=args.force,
        show_details=args.details
    )

    # Возвращаем код выхода
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()