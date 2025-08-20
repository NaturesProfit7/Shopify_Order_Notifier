# test_specific_order.py
"""
Тестовый скрипт для проверки обработки конкретного заказа из Shopify
"""
import base64
import hashlib
import hmac
import json
import requests
import os
from dotenv import load_dotenv

load_dotenv()


def run_order_webhook(order_id: int):
    """
    Симулирует webhook от Shopify для конкретного заказа.
    Сначала получает данные заказа через API, затем отправляет как webhook.
    """

    # 1. Получаем полные данные заказа из Shopify
    print(f"📥 Получаем заказ #{order_id} из Shopify...")

    from app.services.shopify_service import get_order
    try:
        order_data = get_order(order_id)
        print(f"✅ Заказ получен: {order_data.get('name')} от {order_data.get('customer', {}).get('first_name')}")
    except Exception as e:
        print(f"❌ Ошибка получения заказа: {e}")
        return

    # 2. Подготавливаем webhook payload
    webhook_url = "http://localhost:8001/webhooks/shopify/orders"
    secret = os.getenv("SHOPIFY_WEBHOOK_SECRET", "test_secret")

    # Shopify отправляет полные данные заказа в webhook
    payload = order_data

    # 3. Создаем HMAC подпись
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("utf-8")

    print(f"\n📤 Отправляем webhook на {webhook_url}")
    print(f"   Подпись: {signature[:20]}...")

    # 4. Отправляем POST запрос
    try:
        response = requests.post(
            webhook_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": signature,
            },
            timeout=30
        )

        print(f"\n📨 Ответ сервера:")
        print(f"   Статус: {response.status_code}")
        print(f"   Тело: {response.text}")

        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "duplicate":
                print("\n⚠️ Заказ уже был обработан ранее")
            else:
                print("\n✅ Заказ успешно обработан!")
                print("   Проверьте Telegram для подтверждения")
        else:
            print(f"\n❌ Ошибка: {response.status_code}")

    except requests.exceptions.ConnectionError:
        print("\n❌ Не могу подключиться к серверу. Убедитесь, что сервер запущен:")
        print("   uvicorn app.main:app --host 0.0.0.0 --port 8001")
    except Exception as e:
        print(f"\n❌ Ошибка отправки: {e}")


if __name__ == "__main__":
    # ID вашего заказа
    ORDER_ID = 6417067999535

    print("=" * 50)
    print(f"🧪 Тестирование обработки заказа #{ORDER_ID}")
    print("=" * 50)

    run_order_webhook(ORDER_ID)