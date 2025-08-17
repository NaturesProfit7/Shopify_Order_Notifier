# app/services/shopify_service.py
from __future__ import annotations
import os, time
from typing import Any, Dict, Optional
import requests
from dotenv import load_dotenv

load_dotenv()

SHOP_DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN", "").strip() or os.getenv("SHOPIFY_SHOP_DOMAIN", "").strip()
API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-04").strip()
ADMIN_TOKEN = os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", "").strip() or os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()

if not SHOP_DOMAIN or not ADMIN_TOKEN:
    raise RuntimeError("SHOPIFY_STORE_DOMAIN/SHOPIFY_SHOP_DOMAIN или SHOPIFY_ADMIN_ACCESS_TOKEN/SHOPIFY_ACCESS_TOKEN не заданы в .env")

BASE_URL = f"https://{SHOP_DOMAIN}/admin/api/{API_VERSION}"

_session = requests.Session()
_session.headers.update({
    "X-Shopify-Access-Token": ADMIN_TOKEN,   # Admin API токен
    "Accept": "application/json",
})

class ShopifyApiError(RuntimeError):
    pass

def _request_json(method: str, path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    # простые ретраи на 429/5xx
    backoffs = [1, 2, 4]
    for i, pause in enumerate([0] + backoffs):  # первая попытка без паузы
        if pause:
            time.sleep(pause)
        resp = _session.request(method, url, params=params, timeout=30)
        # 429: уважаем Retry-After
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            time.sleep(min(retry_after, 10.0))
            continue
        # 5xx: пробуем ретраить
        if 500 <= resp.status_code < 600 and i < len(backoffs):
            continue
        if resp.status_code >= 400:
            raise ShopifyApiError(f"{resp.status_code} {resp.text}")
        return resp.json()
    raise ShopifyApiError("Rate limited / 5xx после нескольких ретраев")

def get_order(order_id: int | str) -> Dict[str, Any]:
    """
    Возвращает полный заказ по ID через REST Admin API:
    GET /admin/api/{version}/orders/{id}.json  ->  { "order": {...} }
    """
    data = _request_json("GET", f"/orders/{order_id}.json")
    order = data.get("order")
    if not order:
        raise ShopifyApiError("Order not found or malformed response")
    return order
