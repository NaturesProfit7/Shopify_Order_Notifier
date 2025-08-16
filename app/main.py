import json
from app.state import is_processed, mark_processed
from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, base64
from app.config import get_shopify_webhook_secret

from app.services.phone_utils import normalize_ua_phone, pretty_ua_phone
from app.services.vcf_service import build_contact_vcf
from app.services.tg_service import send_text, send_file

app = FastAPI()

def _extract_customer_name(order: dict) -> tuple[str, str]:
    cust = (order.get("customer") or {})
    first = (cust.get("first_name") or "").strip()
    last  = (cust.get("last_name") or "").strip()
    if not first and not last:
        ship = (order.get("shipping_address") or {})
        first = (ship.get("first_name") or "").strip() or first
        last  = (ship.get("last_name") or "").strip() or last
    return first, last

def _extract_phone(order: dict) -> str:
    cust = (order.get("customer") or {})
    ship = (order.get("shipping_address") or {})
    bill = (order.get("billing_address") or {})
    return (
        (cust.get("phone") or "")
        or (ship.get("phone") or "")
        or (bill.get("phone") or "")
        or ""
    )

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

    # (а) Извлекаем ФИО и телефон из payload
    first_name, last_name = _extract_customer_name(event)
    phone_raw = _extract_phone(event)

    # (б) Нормализуем в E.164 (+380XXXXXXXXX)
    phone_e164 = normalize_ua_phone(phone_raw)

    # (в) Генерируем vCard (bytes, filename)
    vcf_bytes, vcf_filename = build_contact_vcf(
        first_name=first_name,
        last_name=last_name,
        order_id=str(order_id),
        phone_e164=phone_e164,  # если None — TEL не попадёт (по нашему билдеру)
    )

    # (г) Подпись к файлу: красивый номер, если удалось распознать
    caption = "Контакт клієнта (vCard)"
    if phone_e164:
        caption += f"\n{pretty_ua_phone(phone_e164)}"
    else:
        caption += "\n⚠️ Номер потребує перевірки"

    # (д) Шлём VCF в Telegram — вторым сообщением по пайплайну
    #     (PDF будет первым, добавим в следующий шаг)
    send_file(vcf_bytes, vcf_filename, caption=caption)

    # (е) Для контроля можно отправить короткий текст
    # send_text(f"✅ VCF відправлено для замовлення #{order_id}")

    return {"status": "ok", "order_id": str(order_id)}