# app/main.py - ИСПРАВЛЕННЫЙ С ПРАВИЛЬНЫМ ОБЪЕКТОМ APP
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

from app.db import get_session
from app.models import Order, OrderStatus

# Expose UI helpers and Telegram helpers for tests
from app.services.menu_ui import orders_list_buttons, order_card_buttons
from app.services.tg_service import send_text_with_buttons, answer_callback_query

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
async def lifespan(app_instance: FastAPI):
    """Управление жизненным циклом приложения"""
    logger.info("Starting application lifespan...")

    try:
        # Импортируем и запускаем бота при старте
        from app.bot.main import start_bot
        logger.info("Starting Telegram bot...")
        bot_task = asyncio.create_task(start_bot())

        # Даем боту время инициализироваться
        await asyncio.sleep(2)
        logger.info("Bot initialization complete")

        yield

    except Exception as e:
        logger.error(f"Error during bot startup: {e}", exc_info=True)
        yield  # Продолжаем работу даже если бот не запустился

    finally:
        # Останавливаем бота при выключении
        logger.info("Stopping application...")
        try:
            from app.bot.main import stop_bot
            await stop_bot()
            logger.info("Bot stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}", exc_info=True)


# СОЗДАЕМ ОБЪЕКТ ПРИЛОЖЕНИЯ
app = FastAPI(
    title="Shopify Order Notifier",
    description="Автоматическая обработка заказов Shopify и уведомления в Telegram",
    version="1.0.0",
    lifespan=lifespan
)


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
    """Проверка состояния сервиса"""
    return {"status": "ok", "timestamp": int(time.time())}


@app.get("/")
def root():
    """Корневой путь"""
    return {
        "service": "Shopify Order Notifier",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "webhook": "/webhooks/shopify/orders",
            "telegram": "/telegram/webhook"
        }
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Minimal handler for Telegram callbacks used in tests."""
    data = await request.json()
    callback = data.get("callback_query")
    if not callback:
        return {"ok": True}

    cb_data = callback.get("data", "")
    cb_id = callback.get("id", "")

    # Handle order list navigation callbacks
    if cb_data.startswith("orders:list:"):
        try:
            _, _, kind, offset_part = cb_data.split(":", 3)
            offset = int(offset_part.split("=")[1])
        except Exception:
            offset = 0
            kind = "all"

        buttons = orders_list_buttons(kind, offset, page_size=10, has_prev=False, has_next=True)
        send_text_with_buttons(f"Список замовлень ({kind}) 1/1", buttons)
        answer_callback_query(cb_id)
        return {"ok": True}

    # Handle order card view callbacks
    if cb_data.startswith("order:") and cb_data.endswith(":view"):
        parts = cb_data.split(":")
        try:
            order_id = int(parts[1])
        except (IndexError, ValueError):
            order_id = 0
        buttons = order_card_buttons(order_id)
        send_text_with_buttons(f"Картка замовлення #{order_id}", buttons)
        answer_callback_query(cb_id)
        return {"ok": True}

    answer_callback_query(cb_id)
    return {"ok": True}


@app.post("/webhooks/shopify/orders")
async def shopify_webhook(request: Request):
    """Обработчик webhook от Shopify - С ИСПРАВЛЕННЫМ СОХРАНЕНИЕМ КОНТАКТНЫХ ДАННЫХ"""
    logger.info("=== WEBHOOK RECEIVED ===")

    # 1) Получаем и валидируем данные
    raw_body = await request.body()
    logger.info(f"Body size: {len(raw_body)} bytes")

    # HMAC валидация
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    secret = get_shopify_webhook_secret()

    if not hmac_header:
        logger.error("Missing X-Shopify-Hmac-Sha256 header")
        raise HTTPException(status_code=403, detail="Missing HMAC header")

    if not secret:
        logger.error("Missing SHOPIFY_WEBHOOK_SECRET")
        raise HTTPException(status_code=500, detail="Missing webhook secret")

    # Shopify использует secret как UTF-8 строку
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

    # 4) Извлекаем данные с НОВОЙ ЛОГИКОЙ адресов
    first_name, last_name, phone_e164 = _extract_customer_data_new_logic(order_full)

    # Логируем сценарий адресов
    shipping = order_full.get('shipping_address', {})
    billing = order_full.get('billing_address', {})
    scenario = "same_address" if addresses_are_same(shipping, billing) else "different_addresses"

    logger.info(f"Address scenario: {scenario}")
    logger.info(f"Contact: {first_name} {last_name}, Phone: {phone_e164}")

    # 5) ИСПРАВЛЕНИЕ: Помечаем как обработанный И обновляем контактные данные
    logger.info(f"Marking order {order_id} as processed with contact data...")

    # Создаем копию данных заказа с обновленными контактными данными
    order_data_with_contact = order_full.copy()

    # Обновляем customer секцию с правильными контактными данными
    if 'customer' not in order_data_with_contact:
        order_data_with_contact['customer'] = {}

    order_data_with_contact['customer']['first_name'] = first_name
    order_data_with_contact['customer']['last_name'] = last_name

    marked = await mark_processed(order_id, order_data_with_contact)
    if not marked:
        log_event("webhook_race_condition", order_id=str(order_id))
        return {"status": "duplicate", "order_id": str(order_id)}

    # 6) ДОПОЛНИТЕЛЬНОЕ ИСПРАВЛЕНИЕ: Обновляем поля контактных данных в БД
    try:
        with get_session() as session:
            order_obj = session.get(Order, order_id)
            if order_obj:
                # Принудительно обновляем контактные данные
                order_obj.customer_first_name = first_name[:100] if first_name else ""
                order_obj.customer_last_name = last_name[:100] if last_name else ""
                if phone_e164:
                    order_obj.customer_phone_e164 = phone_e164[:32]
                session.commit()
                logger.info(f"✅ Updated contact data in DB: {first_name} {last_name}, {phone_e164}")
    except Exception as e:
        logger.error(f"Failed to update contact data in DB: {e}")

    # 7) Отправляем ОТДЕЛЬНОЕ сообщение с кнопкой "Закрити"
    try:
        from app.bot.main import get_bot
        bot = get_bot()
        if not bot:
            logger.error("Bot instance not available!")
            raise HTTPException(status_code=500, detail="Bot not initialized")

        allowed_ids_str = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        manager_ids = [int(uid.strip()) for uid in allowed_ids_str.split(",") if uid.strip()]
        if not manager_ids:
            logger.error("TELEGRAM_ALLOWED_USER_IDS not set or empty!")
            raise HTTPException(status_code=500, detail="No Telegram managers configured")

        # Получаем обновленный объект заказа из БД
        with get_session() as session:
            order_obj = session.get(Order, order_id)
            if not order_obj:
                logger.error(f"Order {order_id} not found in DB after processing")
                raise HTTPException(status_code=500, detail="Database error")

            # WEBHOOK заказ: отправляется ОТДЕЛЬНО (не как navigation!)
            from app.bot.services.message_builder import get_status_emoji, DIVIDER

            # Строим сообщение
            order_no = order_obj.order_number or order_obj.id
            status_emoji = get_status_emoji(order_obj.status)
            customer_name = f"{order_obj.customer_first_name or ''} {order_obj.customer_last_name or ''}".strip() or "Без імені"
            phone = order_obj.customer_phone_e164 if order_obj.customer_phone_e164 else "Не вказано"

            main_message = f"""📦 <b>Замовлення #{order_no}</b> • {status_emoji} Новий
{DIVIDER}
👤 {customer_name}
📱 {phone}"""

            # Добавляем краткую информацию о товарах
            if order_obj.raw_json and order_obj.raw_json.get("line_items"):
                items = order_obj.raw_json["line_items"]
                if items:
                    items_text = []
                    for item in items[:3]:
                        title = item.get("title", "")
                        qty = item.get("quantity", 0)
                        items_text.append(f"• {title} x{qty}")

                    if items_text:
                        main_message += f"\n🛍 <b>Товари:</b> {', '.join(items_text)}"
                        if len(items) > 3:
                            main_message += f" <i>+ще {len(items) - 3}</i>"

                # Сумма
                total = order_obj.raw_json.get("total_price", "")
                currency = order_obj.raw_json.get("currency", "UAH")
                if total:
                    main_message += f"\n💰 <b>Сума:</b> {total} {currency}"

            main_message += f"\n{DIVIDER}"

            from app.bot.routers.shared import get_webhook_order_keyboard
            webhook_keyboard = get_webhook_order_keyboard(order_obj)

            # Отправляем сообщение каждому менеджеру
            from app.bot.routers.shared import add_webhook_message
            for manager_id in manager_ids:
                msg = await bot.send_message(
                    manager_id,
                    main_message,
                    reply_markup=webhook_keyboard
                )
                add_webhook_message(order_id, manager_id, msg.message_id)

            logger.info(f"Webhook order card sent to managers: {manager_ids}")
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


# Добавляем дополнительные эндпойнты для отладки
@app.get("/debug/orders")
async def debug_orders():
    """Отладочный эндпойнт для просмотра заказов"""
    try:
        with get_session() as session:
            orders = session.query(Order).order_by(Order.created_at.desc()).limit(10).all()

            result = []
            for order in orders:
                result.append({
                    "id": order.id,
                    "order_number": order.order_number,
                    "status": order.status.value,
                    "customer_name": f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip(),
                    "customer_phone": order.customer_phone_e164,
                    "created_at": order.created_at.isoformat() if order.created_at else None,
                    "is_processed": order.is_processed
                })

            return {"orders": result, "total": len(result)}

    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8003, reload=True)