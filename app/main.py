import json
from app.state import is_processed, mark_processed
from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, base64
from app.config import get_shopify_webhook_secret

from app.services.phone_utils import normalize_ua_phone, pretty_ua_phone
from app.services.vcf_service import build_contact_vcf
from app.services.tg_service import send_text, send_file

from app.services.pdf_service import build_order_pdf

from app.services.message_templates import render_simple_confirm


import logging, json as _json, time
logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO)

def log_event(event: str, **kwargs):
    payload = {"event": event, "timestamp": int(time.time())}
    payload.update(kwargs)
    logger.info(_json.dumps(payload, ensure_ascii=False))


app = FastAPI()

def _extract_customer_name(order: dict) -> tuple[str, str]:
    cust = (order.get("customer") or {})
    first = (cust.get("first_name") or "").strip()
    last  = (cust.get("last_name") or "").strip()

    if not first and not last:
        ship = (order.get("shipping_address") or {})
        first = (ship.get("first_name") or "").strip() or first
        last  = (ship.get("last_name") or "").strip() or last

    if not first and not last:
        bill = (order.get("billing_address") or {})
        first = (bill.get("first_name") or "").strip() or first
        last  = (bill.get("last_name") or "").strip() or last

    return first, last

def _extract_phone(order: dict) -> str:
    """
    Пытаемся вытащить номер из всех типичных мест Shopify:
    1) customer.phone
    2) order.phone               <-- добавили
    3) customer.default_address.phone
    4) shipping_address.phone
    5) billing_address.phone
    Возвращаем первую непустую строку .strip().
    """
    cust = (order.get("customer") or {})
    default_addr = (cust.get("default_address") or {})
    ship = (order.get("shipping_address") or {})
    bill = (order.get("billing_address") or {})

    for v in (
        cust.get("phone"),
        order.get("phone"),               # <-- НОВОЕ
        default_addr.get("phone"),
        ship.get("phone"),
        bill.get("phone"),
    ):
        if v and str(v).strip():
            return str(v).strip()
    return ""


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/webhooks/shopify/orders")
async def shopify_webhook(request: Request):
    # 1) Сырые байты тела (для HMAC)
    raw_body = await request.body()

    # 2) Валидация подписи Shopify
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    secret = get_shopify_webhook_secret()
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    computed_hmac = base64.b64encode(digest).decode("utf-8")
    if not hmac.compare_digest(computed_hmac, hmac_header or ""):
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    # 3) Парсим JSON
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 4) order_id
    order_id = event.get("id") or event.get("order_id")
    if order_id is None:
        raise HTTPException(status_code=400, detail="order_id is missing in event")

    # 5) Идемпотентность
    if await is_processed(order_id):
        return {"status": "duplicate", "order_id": str(order_id)}

    # 6) Помечаем как обработанный
    await mark_processed(order_id)

    # ---------- Сообщение №1: PDF ----------
    try:
        pdf_bytes, pdf_filename = build_order_pdf(event)
        first_name, last_name = _extract_customer_name(event)
        pdf_caption = f"Замовлення #{event.get('order_number') or event.get('id')} • {(first_name + ' ' + last_name).strip()}".strip()

        for attempt in range(1, 4):
            try:
                send_file(pdf_bytes, pdf_filename, caption=pdf_caption)
                log_event("pdf_sent", order_id=str(order_id), status="ok", attempt=attempt)
                break
            except Exception as e:
                log_event("pdf_sent", order_id=str(order_id), status="error", attempt=attempt, error=str(e))
                if attempt < 3:
                    time.sleep(30)
                else:
                    raise
    except Exception as e:
        # если PDF не ушёл после 3 попыток — ломаем обработку
        raise

    # ---------- Сообщение №2: VCF ----------
    first_name, last_name = _extract_customer_name(event)
    phone_raw = _extract_phone(event)
    log_event("phone_extracted", order_id=str(order_id), phone_raw=phone_raw)

    phone_e164 = normalize_ua_phone(phone_raw)
    log_event("phone_normalized", order_id=str(order_id), phone_e164=phone_e164)

    vcf_bytes, vcf_filename = build_contact_vcf(
        first_name=first_name,
        last_name=last_name,
        order_id=str(order_id),
        phone_e164=phone_e164,
        embed_order_in_n=True,
    )

    caption = "Контакт клієнта (vCard)"
    if phone_e164:
        caption += f"\n{pretty_ua_phone(phone_e164)}"
    else:
        caption += "\n⚠️ Номер потребує перевірки"

    for attempt in range(1, 4):
        try:
            send_file(vcf_bytes, vcf_filename, caption=caption)
            log_event("vcf_sent", order_id=str(order_id), status="ok", attempt=attempt)
            break
        except Exception as e:
            log_event("vcf_sent", order_id=str(order_id), status="error", attempt=attempt, error=str(e))
            if attempt < 3:
                time.sleep(30)
            else:
                raise

    # ---------- Сообщение №3: черновик менеджеру ----------
    draft = render_simple_confirm(event)

    for attempt in range(1, 4):
        try:
            send_text(draft)
            log_event("draft_msg_sent", order_id=str(order_id), status="ok", attempt=attempt)
            break
        except Exception as e:
            log_event("draft_msg_sent", order_id=str(order_id), status="error", attempt=attempt, error=str(e))
            if attempt < 3:
                time.sleep(30)
            else:
                raise

    return {"status": "ok", "order_id": str(order_id)}



    # (е) Для контроля можно отправить короткий текст
    # send_text(f"✅ VCF відправлено для замовлення #{order_id}")

    return {"status": "ok", "order_id": str(order_id)}