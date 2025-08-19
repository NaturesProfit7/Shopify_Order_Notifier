from __future__ import annotations

import os
import sys
import base64
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

# Загрузим .env до остальных импортов
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

# App deps
from app.config import get_shopify_webhook_secret, get_telegram_secret_token
from app.db import get_session
from app.models import Order, OrderStatus
from app.services.message_templates import render_simple_confirm
from app.services.phone_utils import normalize_ua_phone, pretty_ua_phone
from app.services.pdf_service import build_order_pdf
from app.services.vcf_service import build_contact_vcf
from app.services.shopify_service import get_order
from app.services.status_ui import status_title, buttons_for_status
from app.services.tg_service import send_file, send_text_with_buttons

# aiogram
from aiogram.types import Update
from app.bot.dispatcher import build_bot_and_dispatcher

logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO)

def log_event(event: str, **kwargs):
    payload = {"event": event, "ts": int(time.time())}
    payload.update(kwargs)
    logger.info(json.dumps(payload, ensure_ascii=False))

app = FastAPI()

# --- aiogram: один процесс, feed updates из FastAPI ---
BOT, DP = build_bot_and_dispatcher()

@app.on_event("startup")
async def on_startup():
    # Если хочешь, можно тут же проставлять вебхук:
    # hook_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/") + "/tg/webhook"
    # secret = get_telegram_secret_token()
    # if hook_url:
    #     await BOT.set_webhook(url=hook_url, secret_token=secret)
    pass

@app.on_event("shutdown")
async def on_shutdown():
    await BOT.session.close()


# ----------------------------- Health -----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------ Shopify Webhook -------------------------
@app.post("/webhooks/shopify/orders")
async def shopify_orders_webhook(request: Request):
    raw_body = await request.body()
    secret = get_shopify_webhook_secret().encode("utf-8")
    digest = hmac.new(secret, raw_body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode()
    provided = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if not hmac.compare_digest(signature, provided):
        raise HTTPException(status_code=401, detail="Invalid HMAC")

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    order_id = event.get("id") or event.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is missing in event")
    order_id = int(order_id)

    # 3) Получаем полный заказ из Shopify
    try:
        order = get_order(order_id)  # API Shopify
        order_number = str(order.get("order_number") or order.get("name", "").lstrip("#") or order_id)
        cust = (order.get("customer") or {})
        first = (cust.get("first_name") or
                 (order.get("shipping_address") or {}).get("first_name") or
                 (order.get("billing_address") or {}).get("first_name") or "").strip()
        last = (cust.get("last_name") or
                (order.get("shipping_address") or {}).get("last_name") or
                (order.get("billing_address") or {}).get("last_name") or "").strip()

        # телефон
        phone_raw = (
            cust.get("phone") or order.get("phone") or
            (cust.get("default_address") or {}).get("phone") or
            (order.get("shipping_address") or {}).get("phone") or
            (order.get("billing_address") or {}).get("phone") or ""
        )
        phone_e164 = normalize_ua_phone(phone_raw)
    except Exception as e:
        log_event("shopify_get_order_err", order_id=str(order_id), error=str(e))
        raise HTTPException(status_code=502, detail="Failed to fetch order from Shopify")

    # 4) upsert в БД + идемпотентность
    with get_session() as s:
        db = s.get(Order, order_id)
        if db and db.is_processed:
            log_event("skip_duplicate", order_id=str(order_id))
            return {"status": "duplicate", "order_id": str(order_id)}
        if not db:
            db = Order(
                id=order_id,
                order_number=order_number,
                status=OrderStatus.NEW,
                is_processed=False,
                customer_first_name=first or None,
                customer_last_name=last or None,
                customer_phone_e164=phone_e164,
                raw_json=order,
            )
            s.add(db)
        else:
            db.order_number = order_number
            db.customer_first_name = first or None
            db.customer_last_name = last or None
            db.customer_phone_e164 = phone_e164
            db.raw_json = order

    # 5) PDF -> Telegram
    pdf_bytes, pdf_filename = build_order_pdf(order)
    pdf_caption = f"Замовлення #{order_number} • {(first + ' ' + last).strip()}".strip()
    send_file(pdf_bytes, pdf_filename, caption=pdf_caption)

    # 6) VCF -> Telegram
    vcf_bytes, vcf_filename = build_contact_vcf(
        first_name=first, last_name=last,
        order_id=f"#{order_number}", phone_e164=phone_e164, embed_order_in_n=True)
    vcf_caption = "Контакт клієнта (vCard)"
    vcf_caption += f"\n{pretty_ua_phone(phone_e164)}" if phone_e164 else "\n⚠️ Номер потребує перевірки"
    send_file(vcf_bytes, vcf_filename, caption=vcf_caption)

    # 7) Сообщение менеджеру + inline‑кнопки
    full_text = f"Статус: {status_title(OrderStatus.NEW)}\n\n{render_simple_confirm(order)}"
    kb = buttons_for_status(OrderStatus.NEW, order_id)
    msg = send_text_with_buttons(full_text, kb)
    message_id = (msg.get("result") or {}).get("message_id")

    # 8) финализация записи
    with get_session() as s:
        db = s.get(Order, order_id)
        if db:
            db.is_processed = True
            db.chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")
            if message_id:
                db.last_message_id = int(message_id)

    return {"status": "ok", "order_id": str(order_id)}


# --------------------- Telegram webhook → aiogram ---------------------
@app.post("/tg/webhook")
async def telegram_webhook(request: Request):
    # (опционально) проверяем секрет Telegram
    expected = get_telegram_secret_token()
    provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if expected and provided != expected:
        raise HTTPException(status_code=401, detail="Invalid Telegram secret token")

    raw = await request.body()
    update = Update.model_validate_json(raw.decode("utf-8"))
    await DP.feed_update(BOT, update)
    return {"ok": True}
