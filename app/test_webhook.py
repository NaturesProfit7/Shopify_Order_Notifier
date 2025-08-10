import hmac, hashlib, base64
import requests

secret = "test_secret"
body = '{"foo":"bar"}'

# HMAC
digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
signature = base64.b64encode(digest).decode()
print("Signature:", signature)

# POST
resp = requests.post(
    "http://127.0.0.1:8000/webhooks/shopify/orders",
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-Shopify-Hmac-Sha256": signature
    }
)
print("Status:", resp.status_code)
print("Response:", resp.text)