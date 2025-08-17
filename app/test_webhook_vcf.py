# test_webhook_vcf.py
from __future__ import annotations
import argparse, base64, hashlib, hmac, json, time
import requests


def sign_and_send(url: str, secret: str, payload: dict, timeout: int = 15):
    # Готовим ТЕЛО БЕЗ ЛИШНИХ ПРОБЕЛОВ (важно для HMAC)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # Подпись Shopify: base64(HMAC_SHA256(secret, body))
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("utf-8")

    print("=== REQUEST ===")
    print("Payload:", body.decode("utf-8"))
    print("Signature:", signature)

    resp = requests.post(
        url,
        data=body,  # ВАЖНО: data, не json=...
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Hmac-Sha256": signature,
        },
        timeout=timeout,
    )

    print("=== RESPONSE ===")
    print("Status:", resp.status_code)
    print("Body:", resp.text)


# ---------- БАЗА И СЦЕНАРИИ ----------

def base_order(order_id: int) -> dict:
    return {
        "id": order_id,
        "order_number": order_id,
        "customer": {},
        "shipping_address": {},
        "billing_address": {},
    }

def scenario_full_ok(order_id: int) -> dict:
    # Ожидаем: FN "Іван Петренко — #<id>", TEL "+380672326239"
    o = base_order(order_id)
    o["customer"] = {
        "first_name": "Іван",
        "last_name": "Петренко",
        "phone": "+380 (67) 232 62 39",  # «грязный» → нормализуется
    }
    return o

def scenario_fallback_shipping(order_id: int) -> dict:
    # Имя/телефон берём из shipping_address
    o = base_order(order_id)
    o["shipping_address"] = {
        "first_name": "Марія",
        "last_name": "Коваль",
        "phone": "0672326239",  # локальный → +380672326239
    }
    return o

def scenario_no_phone(order_id: int) -> dict:
    # Телефона нет → TEL в VCF отсутствует, в подписи предупреждение
    o = base_order(order_id)
    o["customer"] = {"first_name": "Олег", "last_name": "Сидоренко"}
    return o

def scenario_bad_phone(order_id: int) -> dict:
    # «Кривой» телефон → нормализовать нельзя → TEL нет
    o = base_order(order_id)
    o["customer"] = {"first_name": "Анна", "last_name": "Романюк", "phone": "12345"}
    return o

def scenario_pdf_demo(order_id: int) -> dict:
    return {
        "id": order_id,
        "order_number": order_id,
        "created_at": "2025-08-16T12:34:56+03:00",
        "customer": {"first_name": "Іван", "last_name": "Петренко"},
        "shipping_address": {
            "address1": "вул. Хрещатик, 1",
            "city": "Київ",
            "zip": "01001",
            "country": "Україна",
        },
        "line_items": [
            {"title": "Адресник серце (золото) 30мм", "quantity": 1, "price": "450.00"},
            {"title": "Шнурочок флуоресцентний", "quantity": 1, "price": "50.00"},
            {"title": "Намистинки", "quantity": 1, "price": "50.00"},
        ],
    }


def scenario_root_phone(order_id: int) -> dict:
    o = {
        "id": order_id,
        "order_number": order_id,
        "phone": "+380 (67) 232 62 39",  # номер в корне заказа
        "customer": {"first_name": "Іван", "last_name": "Петренко"},
    }
    return o

def scenario_id_only(order_id: int) -> dict:
    return {"id": order_id}


SCENARIOS = {
    "full_ok": scenario_full_ok,
    "fallback_shipping": scenario_fallback_shipping,
    "no_phone": scenario_no_phone,
    "pdf_demo": scenario_pdf_demo,
    "root_phone": scenario_root_phone,
    "id_only":scenario_id_only,
    "bad_phone": scenario_bad_phone,
}



# ---------- CLI ----------

def parse_args():
    p = argparse.ArgumentParser(description="Shopify webhook VCF tester")
    p.add_argument("--url", default="http://127.0.0.1:8001/webhooks/shopify/orders")
    p.add_argument("--secret", default="test_secret", help="SHOPIFY_WEBHOOK_SECRET")
    p.add_argument("--scenario", choices=SCENARIOS.keys(), default="full_ok")
    p.add_argument("--order-id", type=int, default=int(time.time()),
                   help="По умолчанию unix‑time (удобно для идемпотентности)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    payload = SCENARIOS[args.scenario](args.order_id)
    sign_and_send(args.url, args.secret, payload)
