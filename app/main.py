from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, base64
from app.config import get_shopify_webhook_secret


app = FastAPI()
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/webhooks/shopify/orders")
async def shopify_webhook(request: Request):
    # 1. Читаем "сырое" тело запроса (байты, не текст!)
    raw_body = await request.body()

    # 2. Берём подпись, которую прислал Shopify (из заголовка запроса)
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")

    # 3. Достаём наш секретный ключ из .env
    secret = get_shopify_webhook_secret()

    # 4. Создаём свою подпись из тела запроса и секрета (SHA256)
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()

    # 5. Переводим подпись в base64 (Shopify делает так же)
    computed_hmac = base64.b64encode(digest).decode("utf-8")

    # 6. Сравниваем свою подпись с подписью Shopify
    if not hmac.compare_digest(computed_hmac, hmac_header or ""):
        # Если они разные — возвращаем ошибку 403 (доступ запрещён)
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    # 7. Если всё хорошо — печатаем в консоль и отвечаем "ok"
    print("Webhook verified")
    from app.services.tg_service import send_text
    send_text("✅ Webhook получен и проверен!")

    return {"status": "ok"}