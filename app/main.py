# app/main.py - С ОТЛАДКОЙ HMAC
import json
import asyncio
from contextlib import asynccontextmanager
from app.state import is_processed, mark_processed, update_telegram_info
from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, base64
from app.config import get_shopify_webhook_secret

from app.services.phone_utils import normalize_ua_phone
from app.services.address_utils import get_delivery_and_contact_info, get_contact_name, get_contact_phone_e164, \
    addresses_are_same

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


def _extract_customer_data_new_logic(order: dict) -> tuple[str, str, str]:
    """
    НОВАЯ ЛОГИКА: извлекает данные контактного лица с учетом разных адресов.
    Возвращает (first_name, last_name, phone_e164).
    """
    # Получаем контактную информацию
    _, contact_info = get_delivery_and_contact_info(order)

    # Извлекаем имя контактного лица
    first_name, last_name = get_contact_name(contact_info)

    # Если нет имени в контактной информации - пробуем customer
    if not first_name and not last_name:
        cust = order.get("customer", {})
        first_name = (cust.get("first_name") or "").strip()
        last_name = (cust.get("last_name") or "").strip()

    # Извлекаем телефон контактного лица
    phone_e164 = get_contact_phone_e164(contact_info)

    # Если нет телефона в контактной информации - пробуем другие источники
    if not phone_e164:
        cust = order.get("customer", {})
        default_addr = cust.get("default_address", {})

        for phone_source in [
            cust.get("phone"),
            order.get("phone"),
            default_addr.get("phone"),
        ]:
            if phone_source and str(phone_source).strip():
                phone_e164 = normalize_ua_phone(str(phone_source).strip())
                if phone_e164:
                    break

    return first_name, last_name, phone_e164 or ""


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
    """Обработчик webhook от Shopify - С ОТЛАДКОЙ HMAC"""
    logger.info("=== WEBHOOK RECEIVED ===")

    # 1) Получаем и валидируем данные
    raw_body = await request.body()
    logger.info(f"Body size: {len(raw_body)} bytes")

    # ИСПРАВЛЕННАЯ HMAC ВАЛИДАЦИЯ с правильным secret
    # РАБОЧАЯ HMAC ВАЛИДАЦИЯ
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    secret = get_shopify_webhook_secret()

    if not hmac_header:
        logger.error("Missing X-Shopify-Hmac-Sha256 header")
        raise HTTPException(status_code=403, detail="Missing HMAC header")

    if not secret:
        logger.error("Missing SHOPIFY_WEBHOOK_SECRET")
        raise HTTPException(status_code=500, detail="Missing webhook secret")

    # Shopify использует secret как UTF-8 строку (не hex!)
    secret_bytes = secret.encode('utf-8')
    digest = hmac.new(secret_bytes, raw_body, hashlib.sha256).digest()
    computed_hmac = base64.b64encode(digest).decode('utf-8')

    if not hmac.compare_digest(computed_hmac, hmac_header):
        logger.error(f"HMAC mismatch: computed={computed_hmac}, expected={hmac_header}")
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    logger.info("✅ HMAC validation passed")

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
        from app.services.shopify_service import get_order

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

    # 5) Извлекаем данные с НОВОЙ ЛОГИКОЙ адресов
    first_name, last_name, phone_e164 = _extract_customer_data_new_logic(order_full)

    # Логируем сценарий адресов
    shipping = order_full.get('shipping_address', {})
    billing = order_full.get('billing_address', {})
    scenario = "same_address" if addresses_are_same(shipping, billing) else "different_addresses"

    logger.info(f"Address scenario: {scenario}")
    logger.info(f"Contact: {first_name} {last_name}, Phone: {phone_e164}")

    chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")
    if not chat_id:
        logger.error("TELEGRAM_TARGET_CHAT_ID not set!")
        raise HTTPException(status_code=500, detail="Telegram chat ID not configured")

    # 6) Отправляем ОТДЕЛЬНОЕ сообщение с кнопкой "Закрити"
    bot = get_bot()
    if not bot:
        logger.error("Bot instance not available!")
        raise HTTPException(status_code=500, detail="Bot not initialized")

    try:
        chat_id_int = int(chat_id)

        # Получаем объект заказа из БД
        with get_session() as session:
            order_obj = session.get(Order, order_id)
            if not order_obj:
                logger.error(f"Order {order_id} not found in DB after processing")
                raise HTTPException(status_code=500, detail="Database error")

            # WEBHOOK заказ: отправляется ОТДЕЛЬНО (не как navigation!)
            from app.bot.routers.orders import build_order_card_message
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            main_message = build_order_card_message(order_obj, detailed=True)

            # ПРОСТАЯ клавиатура с кнопкой "Закрити"
            webhook_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                # Кнопки статуса (если NEW)
                [
                    InlineKeyboardButton(text="✅ Зв'язались", callback_data=f"order:{order_id}:contacted"),
                    InlineKeyboardButton(text="❌ Скасування", callback_data=f"order:{order_id}:cancel")
                ] if order_obj.status == OrderStatus.NEW else (
                    [
                        InlineKeyboardButton(text="💰 Оплатили", callback_data=f"order:{order_id}:paid"),
                        InlineKeyboardButton(text="❌ Скасування", callback_data=f"order:{order_id}:cancel")
                    ] if order_obj.status == OrderStatus.WAITING_PAYMENT else []
                ),

                # Файлы
                [
                    InlineKeyboardButton(text="📄 PDF", callback_data=f"order:{order_id}:resend:pdf"),
                    InlineKeyboardButton(text="📱 VCF", callback_data=f"order:{order_id}:resend:vcf")
                ],

                # Реквизиты
                [
                    InlineKeyboardButton(text="💳 Реквізити", callback_data=f"order:{order_id}:payment")
                ],

                # Дополнительные действия (для активных заказов)
                [
                    InlineKeyboardButton(text="💬 Коментар", callback_data=f"order:{order_id}:comment"),
                    InlineKeyboardButton(text="⏰ Нагадати", callback_data=f"order:{order_id}:reminder")
                ] if order_obj.status in [OrderStatus.NEW, OrderStatus.WAITING_PAYMENT] else [],

                # КНОПКА ЗАКРЫТЬ для webhook заказов
                [
                    InlineKeyboardButton(text="❌ Закрити", callback_data=f"webhook:{order_id}:close")
                ]
            ])

            # Отправляем ОТДЕЛЬНОЕ сообщение (НЕ через navigation!)
            webhook_msg = await bot.send_message(
                chat_id=chat_id_int,
                text=main_message,
                reply_markup=webhook_keyboard
            )

            # Трекаем как WEBHOOK сообщение
            from app.bot.routers.shared import add_webhook_message
            add_webhook_message(order_id, webhook_msg.message_id)

            logger.info(f"Webhook order card sent with 'Закрити' button: message_id {webhook_msg.message_id}")
            logger.info(f"Contact identified: {first_name} {last_name}")
            log_event("webhook_processed", order_id=str(order_id), status="success", scenario=scenario,
                      contact_name=f"{first_name} {last_name}")

    except Exception as e:
        logger.error(f"Failed to send via bot: {e}", exc_info=True)
        log_event("bot_send_error", order_id=str(order_id), error=str(e))
        raise HTTPException(status_code=500, detail="Failed to send to Telegram")

    logger.info(f"=== WEBHOOK PROCESSED SUCCESSFULLY for order {order_id} (scenario: {scenario}) ===")
    return {"status": "ok", "order_id": str(order_id), "scenario": scenario,
            "contact_name": f"{first_name} {last_name}"}