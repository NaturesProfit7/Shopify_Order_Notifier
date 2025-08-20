import requests
import json
import base64
import hashlib
import hmac

# Простой тест webhook с минимальными данными
url = "http://localhost:8003/webhooks/shopify/orders"
secret = b"test_secret"

# Минимальный payload
payload = {"id": 6417067999535}
body = json.dumps(payload).encode('utf-8')

# Создаем подпись
signature = base64.b64encode(
    hmac.new(secret, body, hashlib.sha256).digest()
).decode('utf-8')

print(f"Sending to: {url}")
print(f"Payload: {payload}")
print(f"Signature: {signature[:20]}...")

# Отправляем
response = requests.post(
    url,
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-Shopify-Hmac-Sha256": signature
    },
    timeout=5
)

print(f"\nResponse status: {response.status_code}")
print(f"Response body: {response.text}")

# Также проверим health endpoint
health = requests.get("http://localhost:8003/health")
print(f"\nHealth check: {health.status_code} - {health.text}")