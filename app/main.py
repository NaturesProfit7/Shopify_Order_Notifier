import json
import asyncio
from contextlib import asynccontextmanager
from app.state import is_processed, mark_processed, update_telegram_info
from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, base64
from app.config import get_shopify_webhook_secret

from app.services.phone_utils import normalize_ua_phone, pretty_ua_phone
from app.services.vcf_service import build_contact_vcf
from app.services.pdf_service import build_order_pdf
from app.services.shopify_service import get_order
from app.services.tg_service import send_file, send_text_with_buttons

from app.bot.main import start_bot, stop_bot, get_bot
from app.bot.services.message_builder import build_order_message
from app.bot.keyboards import get_order_keyboard
from app.db import get_session
from app.models import Order

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


@app.post("/webhooks/shopify/orders")
async def shopify_webhook(request: Request):
    logger.info("=== WEBHOOK RECEIVED ===")

    # 1) Сырые байты тела (для HMAC)
    raw_body = await request.body()
    logger.info(f"Body size: {len(raw_body)} bytes")

    # 2) Валидация подписи Shopify
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    secret = get_shopify_webhook_secret()
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    computed_hmac = base64.b64encode(digest).decode("utf-8")

    if not hmac.compare_digest(computed_hmac, hmac_header or ""):
        logger.error(f"HMAC mismatch! Expected: {computed_hmac[:20]}..., Got: {(hmac_header or '')[:20]}...")
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    logger.info("HMAC validation passed")

    # 3) Парсим JSON
    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 4) order_id
    order_id = event.get("id") or event.get("order_id")
    if order_id is None:
        logger.error("No order_id in event")
        raise HTTPException(status_code=400, detail="order_id is missing in event")

    logger.info(f"Processing order_id: {order_id}")

    # 5) Идемпотентность через БД
    if await is_processed(order_id):
        log_event("webhook_duplicate", order_id=str(order_id))
        return {"status": "duplicate", "order_id": str(order_id)}

    # 6) Тянем полный заказ из Shopify
    try:
        logger.info(f"Fetching full order {order_id} from Shopify...")
        order_full = get_order(order_id)
        pretty_order_no = _display_order_number(order_full, order_id)
        log_event("shopify_get_order_ok", order_id=str(order_id), order_no=pretty_order_no)
    except Exception as e:
        logger.error(f"Failed to fetch order from Shopify: {e}")
        log_event("shopify_get_order_err", order_id=str(order_id), error=str(e))
        raise HTTPException(status_code=502, detail="Failed to fetch order from Shopify")

    # 7) Помечаем как обработанный в БД
    logger.info(f"Marking order {order_id} as processed...")
    marked = await mark_processed(order_id, order_full)
    if not marked:
        log_event("webhook_race_condition", order_id=str(order_id))
        return {"status": "duplicate", "order_id": str(order_id)}

    # Извлекаем данные
    first_name, last_name = _extract_customer_name(order_full)
    phone_raw = _extract_phone(order_full)
    phone_e164 = normalize_ua_phone(phone_raw)

    logger.info(f"Customer: {first_name} {last_name}, Phone: {phone_e164}")

    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")
    if not chat_id:
        logger.error("TELEGRAM_TARGET_CHAT_ID not set!")
        raise HTTPException(status_code=500, detail="Telegram chat ID not configured")

    await update_telegram_info(order_id, chat_id=chat_id)

    # Генерируем файлы
    logger.info("Generating PDF and VCF files...")
    pdf_bytes, pdf_filename = build_order_pdf(order_full)
    vcf_bytes, vcf_filename = build_contact_vcf(
        first_name=first_name,
        last_name=last_name,
        order_id=pretty_order_no,
        phone_e164=phone_e164,
        embed_order_in_n=True,
    )
    logger.info(f"Files generated: {pdf_filename}, {vcf_filename}")

    # Пытаемся отправить через aiogram бота
    bot = get_bot()
    logger.info(f"Bot instance: {bot is not None}")

    sent_via_bot = False

    if bot and chat_id:
        try:
            logger.info("Attempting to send via aiogram bot...")
            # Получаем объект заказа из БД для построения сообщения
            with get_session() as session:
                order_obj = session.get(Order, order_id)
                if order_obj:
                    message_text = build_order_message(order_obj)
                    keyboard = get_order_keyboard(order_obj)

                    # Отправляем файлы и сообщение через aiogram
                    from aiogram.types import BufferedInputFile

                    # 1. Отправляем PDF
                    pdf_caption = f"📦 Замовлення #{pretty_order_no} • {first_name} {last_name}".strip()
                    logger.info(f"Sending PDF to chat {chat_id}...")
                    await bot.send_document(
                        chat_id=int(chat_id),  # Важно: преобразуем в int
                        document=BufferedInputFile(pdf_bytes, pdf_filename),
                        caption=pdf_caption
                    )
                    logger.info("PDF sent successfully")

                    # 2. Отправляем VCF
                    vcf_caption = "Контакт клієнта (vCard)"
                    if phone_e164:
                        vcf_caption += f"\n{pretty_ua_phone(phone_e164)}"
                    else:
                        vcf_caption += "\n⚠️ Номер потребує перевірки"

                    logger.info(f"Sending VCF to chat {chat_id}...")
                    await bot.send_document(
                        chat_id=int(chat_id),  # Важно: преобразуем в int
                        document=BufferedInputFile(vcf_bytes, vcf_filename),
                        caption=vcf_caption
                    )
                    logger.info("VCF sent successfully")

                    # 3. Отправляем сообщение с кнопками
                    logger.info(f"Sending message with buttons to chat {chat_id}...")
                    button_message = await bot.send_message(
                        chat_id=int(chat_id),  # Важно: преобразуем в int
                        text=message_text,
                        reply_markup=keyboard
                    )
                    logger.info(f"Message sent, id: {button_message.message_id}")

                    # Сохраняем ID сообщения с кнопками
                    await update_telegram_info(order_id, message_id=button_message.message_id)

                    sent_via_bot = True
                    log_event("telegram_sent_via_bot", order_id=str(order_id), status="ok")
                else:
                    logger.error(f"Order {order_id} not found in DB")

        except Exception as e:
            logger.error(f"Failed to send via bot: {e}", exc_info=True)
            log_event("bot_send_error", order_id=str(order_id), error=str(e))
            sent_via_bot = False
    else:
        logger.warning(f"Bot not available or chat_id not set. Bot: {bot}, chat_id: {chat_id}")

    # Если не удалось отправить через бота, используем старый метод
    if not sent_via_bot:
        try:
            logger.info("Fallback to legacy HTTP API method...")

            # Отправляем PDF
            pdf_caption = f"Замовлення #{pretty_order_no} • {(first_name + ' ' + last_name).strip()}".strip()
            logger.info("Sending PDF via HTTP API...")
            send_file(pdf_bytes, pdf_filename, caption=pdf_caption)
            log_event("pdf_sent_legacy", order_id=str(order_id), status="ok")

            # Отправляем VCF
            vcf_caption = "Контакт клієнта (vCard)"
            if phone_e164:
                vcf_caption += f"\n{pretty_ua_phone(phone_e164)}"
            else:
                vcf_caption += "\n⚠️ Номер потребує перевірки"

            logger.info("Sending VCF via HTTP API...")
            send_file(vcf_bytes, vcf_filename, caption=vcf_caption)
            log_event("vcf_sent_legacy", order_id=str(order_id), status="ok")

            # Отправляем текст с кнопками через HTTP API
            with get_session() as session:
                order_obj = session.get(Order, order_id)
                if order_obj:
                    message_text = build_order_message(order_obj)
                    keyboard = get_order_keyboard(order_obj)

                    # Преобразуем клавиатуру aiogram в формат для HTTP API
                    buttons_for_api = []
                    if keyboard and keyboard.inline_keyboard:
                        for row in keyboard.inline_keyboard:
                            api_row = []
                            for button in row:
                                api_row.append({
                                    "text": button.text,
                                    "callback_data": button.callback_data
                                })
                            buttons_for_api.append(api_row)

                    logger.info("Sending message with buttons via HTTP API...")
                    result = send_text_with_buttons(message_text, buttons_for_api)

                    # Сохраняем message_id
                    if result and "result" in result:
                        message_id = result["result"].get("message_id")
                        if message_id:
                            await update_telegram_info(order_id, message_id=message_id)

                    log_event("text_sent_legacy", order_id=str(order_id), status="ok")
                    logger.info("All messages sent via legacy method")

        except Exception as e:
            logger.error(f"Failed to send via legacy method: {e}", exc_info=True)
            log_event("legacy_send_error", order_id=str(order_id), error=str(e))
            raise HTTPException(status_code=500, detail="Failed to send to Telegram")

    log_event("webhook_processed", order_id=str(order_id))
    logger.info(f"=== WEBHOOK PROCESSED SUCCESSFULLY for order {order_id} ===")
    return {"status": "ok", "order_id": str(order_id)}