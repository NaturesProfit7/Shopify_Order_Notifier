# app/main.py
import json
import asyncio
from contextlib import asynccontextmanager
from app.state import is_processed, mark_processed, update_telegram_info
from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, base64
from app.config import get_shopify_webhook_secret

from app.services.phone_utils import normalize_ua_phone
from app.services.vcf_service import build_contact_vcf
from app.services.pdf_service import build_order_pdf
from app.services.shopify_service import get_order

from app.bot.main import start_bot, stop_bot, get_bot
from app.db import get_session
from app.models import Order, OrderStatus

import logging, json as _json, time
import os

# Настройка детального логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("app.main")


def log_event(event: str, **kwargs):
    payload = {"event": event, "timestamp": int(time.time())}
    payload.update(kwargs)
    logger.info(_json.dumps(payload, ensure_ascii=False))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    logger.info("Starting application lifespan...")
    # Запускаем бота при старте
    bot_task = asyncio.create_task(start_bot())
    # Даем боту время инициализироваться
    await asyncio.sleep(2)
    logger.info("Bot initialization complete")
    yield
    # Останавливаем бота при выключении
    logger.info("Stopping application...")
    await stop_bot()


app = FastAPI(lifespan=lifespan)


def _extract_customer_name(order: dict) -> tuple[str, str]:
    cust = (order.get("customer") or {})
    first = (cust.get("first_name") or "").strip()
    last = (cust.get("last_name") or "").strip()

    if not first and not last:
        ship = (order.get("shipping_address") or {})
        first = (ship.get("first_name") or "").strip() or first
        last = (ship.get("last_name") or "").strip() or last

    if not first and not last:
        bill = (order.get("billing_address") or {})
        first = (bill.get("first_name") or "").strip() or first
        last = (bill.get("last_name") or "").strip() or last

    return first, last


def _extract_phone(order: dict) -> str:
    """Извлекаем телефон из всех возможных мест"""
    cust = (order.get("customer") or {})
    default_addr = (cust.get("default_address") or {})
    ship = (order.get("shipping_address") or {})
    bill = (order.get("billing_address") or {})

    for v in (
            cust.get("phone"),
            order.get("phone"),
            default_addr.get("phone"),
            ship.get("phone"),
            bill.get("phone"),
    ):
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _display_order_number(order: dict, fallback_id: int | str) -> str:
    """Человеко-читаемый номер заказа"""
    num = order.get("order_number")
    if num:
        return str(num)
    name = order.get("name")
    if isinstance(name, str) and name.lstrip("#").isdigit():
        return name.lstrip("#")
    return str(fallback_id)


@app.get("/health")
def health():
    return {"status": "ok"}


# app/main.py - ЗАМЕНИТЕ ТОЛЬКО ФУНКЦИЮ shopify_webhook

@app.post("/webhooks/shopify/orders")
async def shopify_webhook(request: Request):
    """Обработчик webhook от Shopify - исправленная версия"""
    logger.info("=== WEBHOOK RECEIVED ===")

    # 1) Получаем и валидируем данные
    raw_body = await request.body()
    logger.info(f"Body size: {len(raw_body)} bytes")

    # Валидация HMAC
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    secret = get_shopify_webhook_secret()
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    computed_hmac = base64.b64encode(digest).decode("utf-8")

    if not hmac.compare_digest(computed_hmac, hmac_header or ""):
        logger.error(f"HMAC mismatch!")
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    logger.info("HMAC validation passed")

    # Парсим JSON
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Получаем order_id
    order_id = event.get("id") or event.get("order_id")
    if order_id is None:
        logger.error("No order_id in event")
        raise HTTPException(status_code=400, detail="order_id is missing")

    logger.info(f"Processing order_id: {order_id}")

    # 2) Проверяем идемпотентность
    if await is_processed(order_id):
        log_event("webhook_duplicate", order_id=str(order_id))
        return {"status": "duplicate", "order_id": str(order_id)}

    # 3) Получаем полные данные заказа
    try:
        # Если webhook содержит полные данные - используем их
        if len(event) > 5 and "line_items" in event:  # Полные данные заказа
            order_full = event
            logger.info(f"Using full order data from webhook")
        else:
            # Если только ID - получаем полные данные
            logger.info(f"Fetching full order {order_id} from Shopify...")
            order_full = get_order(order_id)

        pretty_order_no = _display_order_number(order_full, order_id)
        log_event("order_data_ok", order_id=str(order_id), order_no=pretty_order_no)

    except Exception as e:
        logger.error(f"Failed to get order data: {e}")
        log_event("order_data_err", order_id=str(order_id), error=str(e))

        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Не падаем, если не можем получить данные
        order_full = {
            "id": order_id,
            "order_number": order_id,
            "customer": {},
            "line_items": [],
            "total_price": "0.00",
            "currency": "UAH"
        }
        pretty_order_no = str(order_id)
        logger.warning(f"Using minimal order data for order {order_id}")

    # 4) Помечаем как обработанный
    logger.info(f"Marking order {order_id} as processed...")
    marked = await mark_processed(order_id, order_full)
    if not marked:
        log_event("webhook_race_condition", order_id=str(order_id))
        return {"status": "duplicate", "order_id": str(order_id)}

    # 5) Извлекаем данные
    first_name, last_name = _extract_customer_name(order_full)
    phone_raw = _extract_phone(order_full)
    phone_e164 = normalize_ua_phone(phone_raw)

    logger.info(f"Customer: {first_name} {last_name}, Phone: {phone_e164}")

    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")
    if not chat_id:
        logger.error("TELEGRAM_TARGET_CHAT_ID not set!")
        raise HTTPException(status_code=500, detail="Telegram chat ID not configured")

    # 6) Отправляем через aiogram бота
    bot = get_bot()
    if not bot:
        logger.error("Bot instance not available!")
        raise HTTPException(status_code=500, detail="Bot not initialized")

    try:
        from aiogram.types import BufferedInputFile

        chat_id_int = int(chat_id)

        # Получаем объект заказа из БД
        with get_session() as session:
            order_obj = session.get(Order, order_id)
            if not order_obj:
                logger.error(f"Order {order_id} not found in DB after processing")
                raise HTTPException(status_code=500, detail="Database error")

            # НОВЫЙ ФОРМАТ: Основное сообщение с кнопками управления
            from app.bot.routers.callbacks import build_order_card_message, get_order_card_keyboard

            main_message = build_order_card_message(order_obj, detailed=True)
            main_keyboard = get_order_card_keyboard(order_obj)

            main_msg = await bot.send_message(
                chat_id=chat_id_int,
                text=main_message,
                reply_markup=main_keyboard
            )

            # Сохраняем ID основного сообщения для редактирования
            await update_telegram_info(
                order_id,
                chat_id=str(chat_id),
                message_id=main_msg.message_id
            )

            # АВТОМАТИЧЕСКИ НЕ ОТПРАВЛЯЕМ PDF/VCF - только по кнопкам
            # Это убирает дублирование и дает больше контроля менеджеру

            logger.info(f"Main order message sent successfully for order {order_id}")
            log_event("webhook_processed", order_id=str(order_id), status="success")

    except Exception as e:
        logger.error(f"Failed to send via bot: {e}", exc_info=True)
        log_event("bot_send_error", order_id=str(order_id), error=str(e))
        raise HTTPException(status_code=500, detail="Failed to send to Telegram")

    logger.info(f"=== WEBHOOK PROCESSED SUCCESSFULLY for order {order_id} ===")
    return {"status": "ok", "order_id": str(order_id)}