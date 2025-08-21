# app/services/shopify_service.py
from __future__ import annotations
import os, time
from typing import Any, Dict, Optional
import requests
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

# Получаем настройки из переменных окружения
SHOP_DOMAIN = (
        os.getenv("SHOPIFY_STORE_DOMAIN", "").strip()
        or os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip()
)
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2024-10").strip()
ADMIN_TOKEN = (
        os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", "").strip()
        or os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()
)

# Проверяем обязательные настройки
if not SHOP_DOMAIN:
    raise RuntimeError(
        "SHOPIFY_STORE_DOMAIN или SHOPIFY_SHOP_DOMAIN не заданы в .env. "
        "Укажите домен вашего магазина (example.myshopify.com)"
    )

if not ADMIN_TOKEN:
    raise RuntimeError(
        "SHOPIFY_ADMIN_ACCESS_TOKEN или SHOPIFY_ACCESS_TOKEN не заданы в .env. "
        "Получите токен в админке Shopify (Apps > Develop apps)"
    )

# Убираем протокол из домена если есть
SHOP_DOMAIN = SHOP_DOMAIN.replace("https://", "").replace("http://", "")

# Если домен не содержит .myshopify.com, добавляем
if not SHOP_DOMAIN.endswith('.myshopify.com'):
    if '.' not in SHOP_DOMAIN:
        SHOP_DOMAIN = f"{SHOP_DOMAIN}.myshopify.com"

BASE_URL = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}"

logger.info(f"Shopify API configured: {BASE_URL}")

# Создаем сессию с настройками
_session = requests.Session()
_session.headers.update({
    "X-Shopify-Access-Token": ADMIN_TOKEN,
    "Accept": "application/json",
    "User-Agent": "Shopify-Order-Notifier/1.0"
})


class ShopifyApiError(Exception):
    """Ошибка API Shopify"""

    def __init__(self, message: str, status_code: int = 0, response_text: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


def _request_json(method: str, path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Выполняет HTTP запрос к Shopify API с обработкой ошибок и ретраями.
    """
    url = f"{BASE_URL}{path}"
    logger.debug(f"Making {method} request to {url}")

    # Настройки ретраев: пауза между попытками
    backoffs = [1, 2, 4, 8]  # 1, 2, 4, 8 секунд

    last_exception = None

    for attempt, pause in enumerate([0] + backoffs):  # Первая попытка без паузы
        if pause > 0:
            logger.info(f"Shopify API retry {attempt}/{len(backoffs)} after {pause}s pause")
            time.sleep(pause)

        try:
            response = _session.request(method, url, params=params, timeout=30)

            # Обработка rate limiting (429)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "2"))
                if retry_after <= 10:  # Не ждем больше 10 секунд
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue
                else:
                    raise ShopifyApiError(
                        f"Rate limited with long retry-after: {retry_after}s",
                        status_code=429,
                        response_text=response.text
                    )

            # Успешный ответ
            if 200 <= response.status_code < 300:
                try:
                    return response.json()
                except requests.exceptions.JSONDecodeError:
                    raise ShopifyApiError(
                        f"Invalid JSON response from Shopify API",
                        status_code=response.status_code,
                        response_text=response.text[:500]
                    )

            # Ошибки клиента (4xx) - не ретраим
            if 400 <= response.status_code < 500:
                error_msg = f"Shopify API client error: {response.status_code}"
                try:
                    error_data = response.json()
                    if "errors" in error_data:
                        error_msg += f" - {error_data['errors']}"
                except:
                    error_msg += f" - {response.text[:200]}"

                raise ShopifyApiError(
                    error_msg,
                    status_code=response.status_code,
                    response_text=response.text
                )

            # Ошибки сервера (5xx) - можно ретраить
            if 500 <= response.status_code < 600:
                last_exception = ShopifyApiError(
                    f"Shopify API server error: {response.status_code}",
                    status_code=response.status_code,
                    response_text=response.text[:200]
                )
                if attempt < len(backoffs):
                    logger.warning(f"Server error {response.status_code}, will retry")
                    continue
                else:
                    raise last_exception

            # Неожиданный статус код
            raise ShopifyApiError(
                f"Unexpected status code: {response.status_code}",
                status_code=response.status_code,
                response_text=response.text[:200]
            )

        except requests.exceptions.Timeout:
            last_exception = ShopifyApiError("Request timeout")
            if attempt < len(backoffs):
                logger.warning("Request timeout, will retry")
                continue
            else:
                raise last_exception

        except requests.exceptions.ConnectionError as e:
            last_exception = ShopifyApiError(f"Connection error: {str(e)}")
            if attempt < len(backoffs):
                logger.warning(f"Connection error, will retry: {e}")
                continue
            else:
                raise last_exception

        except requests.exceptions.RequestException as e:
            # Общие ошибки requests - не ретраим
            raise ShopifyApiError(f"Request error: {str(e)}")

    # Если дошли сюда - все попытки исчерпаны
    if last_exception:
        raise last_exception
    else:
        raise ShopifyApiError("All retry attempts failed")


def get_order(order_id: int | str) -> Dict[str, Any]:
    """
    Получает полный заказ по ID через REST Admin API.

    Returns:
        Dict с данными заказа

    Raises:
        ShopifyApiError: При ошибках API или сети
    """
    try:
        order_id = int(order_id)
    except (ValueError, TypeError):
        raise ShopifyApiError(f"Invalid order_id: {order_id}")

    logger.info(f"Fetching order {order_id} from Shopify")

    try:
        data = _request_json("GET", f"/orders/{order_id}.json")

        order = data.get("order")
        if not order:
            raise ShopifyApiError(
                f"Order {order_id} not found or malformed response",
                response_text=str(data)[:200]
            )

        logger.info(f"Successfully fetched order {order_id}")
        return order

    except ShopifyApiError:
        # Пробросим наши ошибки как есть
        raise
    except Exception as e:
        # Неожиданные ошибки
        logger.error(f"Unexpected error fetching order {order_id}: {e}")
        raise ShopifyApiError(f"Unexpected error: {str(e)}")


def test_connection() -> bool:
    """
    Тестирует подключение к Shopify API.

    Returns:
        True если подключение работает
    """
    try:
        logger.info("Testing Shopify API connection...")

        # Пробуем получить информацию о магазине
        data = _request_json("GET", "/shop.json")

        shop = data.get("shop", {})
        shop_name = shop.get("name", "Unknown")
        shop_domain = shop.get("domain", "Unknown")

        logger.info(f"✅ Shopify API connection successful: {shop_name} ({shop_domain})")
        return True

    except ShopifyApiError as e:
        logger.error(f"❌ Shopify API connection failed: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error testing connection: {e}")
        return False


def get_recent_orders(limit: int = 10) -> list[Dict[str, Any]]:
    """
    Получает список последних заказов для тестирования.

    Args:
        limit: Количество заказов (максимум 250)

    Returns:
        Список заказов
    """
    logger.info(f"Fetching {limit} recent orders")

    try:
        data = _request_json("GET", "/orders.json", params={
            "limit": min(limit, 250),
            "status": "any",
            "fields": "id,order_number,name,created_at,customer"
        })

        orders = data.get("orders", [])
        logger.info(f"Found {len(orders)} recent orders")
        return orders

    except ShopifyApiError:
        raise
    except Exception as e:
        raise ShopifyApiError(f"Unexpected error fetching orders: {str(e)}")


# Тестируем подключение при импорте модуля (только в dev режиме)
if __name__ == "__main__":
    # Запускается только при прямом вызове файла
    test_connection()