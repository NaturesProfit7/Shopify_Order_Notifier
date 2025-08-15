import json
from app.state import is_processed, mark_processed
from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, base64
from app.config import get_shopify_webhook_secret


app = FastAPI()
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/webhooks/shopify/orders")
async def shopify_webhook(request: Request):
    # 1) Сырые байты тела (для HMAC)
    raw_body = await request.body()

    # 2) Валидация подписи Shopify (оставь как у тебя реализовано)
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    secret = get_shopify_webhook_secret()
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    computed_hmac = base64.b64encode(digest).decode("utf-8")
    if not hmac.compare_digest(computed_hmac, hmac_header or ""):
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    # 3) Парсим JSON (уже после HMAC, чтобы не трогать raw_body до проверки)
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 4) Достаём order_id (для orders/create это обычно event['id'])
    order_id = event.get("id") or event.get("order_id")
    if order_id is None:
        raise HTTPException(status_code=400, detail="order_id is missing in event")

    # 5) Идемпотентность: если уже обрабатывали — выходим
    if await is_processed(order_id):
        # Можно залогировать duplicate, но для простоты ответим явно
        return {"status": "duplicate", "order_id": str(order_id)}

    # 6) Помечаем как обработанный
    await mark_processed(order_id)

    # 7) ВРЕМЕННО: шлём тестовый текст в TG (из шага 3), чтобы видеть, что дошли сюда
    from app.services.tg_service import send_text
    send_text(f"✅ New order event accepted: #{order_id}")

    return {"status": "ok", "order_id": str(order_id)}