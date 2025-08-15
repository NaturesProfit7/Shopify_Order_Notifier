import hmac, hashlib, base64
import requests

secret = "test_secret"           # как в .env
body = '{"id": 1}'               # теперь тело содержит order_id (id)

# HMAC ровно от этих байт
digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
signature = base64.b64encode(digest).decode()
print("Signature:", signature)

resp = requests.post(
    "http://127.0.0.1:8000/webhooks/shopify/orders",
    data=body,  # ВАЖНО: data, не json=..., чтобы байты совпали 1:1
    headers={
        "Content-Type": "application/json",
        "X-Shopify-Hmac-Sha256": signature
    }
)
print("Status:", resp.status_code)
print("Response:", resp.text)
