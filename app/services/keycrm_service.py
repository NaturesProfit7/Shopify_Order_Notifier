import os
import re
import logging
from datetime import datetime

import pytz
import requests
from dotenv import load_dotenv

from app.services.order_fields import (
    DELIVERY_SERVICE,
    build_header_blocks,
    get_delivery_details,
    format_money,
    get_buyer_comment,
    get_checkout_id,
    get_parties,
    get_payment_info,
    render_header_text,
)

load_dotenv()

logger = logging.getLogger(__name__)

KEYCRM_API_KEY = os.getenv("KEYCRM_API_KEY", "")
KEYCRM_SOURCE_ID = int(os.getenv("KEYCRM_SOURCE_ID", "2"))
KEYCRM_BASE_URL = "https://openapi.keycrm.app/v1"
KEYCRM_APP_URL = "https://timosh-design.keycrm.app/app/orders/view"
KEYCRM_BUYER_URL = "https://timosh-design.keycrm.app/app/clients"

# «Новая почта фоп» в справочнике служб доставки keyCRM
# (GET /order/delivery-service), source_name = novaposhta
KEYCRM_DELIVERY_SERVICE_ID = int(os.getenv("KEYCRM_DELIVERY_SERVICE_ID", "2"))

COMMENT_DIVIDER = "———"

KYIV_TZ = pytz.timezone("Europe/Kyiv")

# Property names (lowercase for comparison)
_PROP_PHONE = "номер телефону"
_PROP_SECOND = "другий номер або коротенька фраза"

_session = requests.Session()
_session.headers.update({
    "Authorization": f"Bearer {KEYCRM_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
})


def create_crm_buyer(order) -> dict:
    """Create buyer in keyCRM. Returns {"id": int, "url": str}.
    Designed to run in a thread via asyncio.run_in_executor."""
    raw = order.raw_json or {}

    first_name = (order.customer_first_name or "").strip()
    last_name = (order.customer_last_name or "").strip()
    full_name = f"{first_name} {last_name}".strip() or "Без імені"

    phone = order.customer_phone_e164 or None
    # пошта замовника, а не отримувача
    email = get_parties(raw)["customer"]["email"] or raw.get("email") or None

    body = {"full_name": full_name}
    if phone:
        body["phone"] = [phone]
    if email:
        body["email"] = [email]

    response = _session.post(f"{KEYCRM_BASE_URL}/buyer", json=body, timeout=30)
    response.raise_for_status()

    buyer_id = response.json()["id"]
    return {"id": buyer_id, "url": f"{KEYCRM_BUYER_URL}/{buyer_id}"}


def find_buyer_by_phone(phone: str) -> dict | None:
    """Search buyer in keyCRM by phone. Returns {"id": int, "url": str} or None.
    Designed to run in a thread via asyncio.run_in_executor."""
    response = _session.get(
        f"{KEYCRM_BASE_URL}/buyer",
        params={"filter[buyer_phone]": phone, "limit": 1},
        timeout=30,
    )
    response.raise_for_status()

    data = response.json().get("data") or []
    if not data:
        return None

    buyer_id = data[0]["id"]
    return {"id": buyer_id, "url": f"{KEYCRM_BUYER_URL}/{buyer_id}"}


def create_crm_order(order) -> dict:
    """Create order in keyCRM. Returns {"id": int, "url": str}.
    Designed to run in a thread via asyncio.run_in_executor."""
    raw = order.raw_json or {}

    first_name = (order.customer_first_name or "").strip()
    last_name = (order.customer_last_name or "").strip()
    full_name = f"{first_name} {last_name}".strip() or "Без імені"

    parties = get_parties(raw)
    email = parties["customer"]["email"] or raw.get("email") or None

    body = {
        "source_id": KEYCRM_SOURCE_ID,
        "source_uuid": str(order.order_number or order.id),
        "buyer": {
            "full_name": full_name,
            "phone": order.customer_phone_e164 or None,
            "email": email,
        },
        "manager_comment": _format_manager_comment(raw, order.comment),
    }

    # Коментар покупця з оформлення замовлення — в окреме поле keyCRM
    buyer_comment = get_buyer_comment(raw)
    if buyer_comment:
        body["buyer_comment"] = buyer_comment

    # Адреса доставки і отримувач. Пробуємо від найповнішого варіанту до
    # найпростішого: якщо keyCRM не прийме прив'язку складу — замовлення все
    # одно створиться, максимум без неї (див. _create_order_with_fallback)
    shipping_variants = _build_shipping_variants(raw, parties)

    crm_id, shipping_kind, degraded = _create_order_with_fallback(body, shipping_variants)
    return {
        "id": crm_id,
        "url": f"{KEYCRM_APP_URL}/{crm_id}",
        "shipping_kind": shipping_kind,
        "shipping_degraded": degraded,
    }


def _build_shipping_variants(raw: dict, parties: dict) -> list[tuple[str, dict | None]]:
    """Варианты блока `shipping` от полного к пустому, каждый со своим видом:

    * `warehouse` — адрес + привязка отделения/почтомата Нової Пошти
    * `courier`   — адрес курьерской доставки (склада у неё нет)
    * `address`   — только текстовый адрес, без привязки
    * `none`      — без блока доставки вообще
    * `empty`     — в заказе нет адреса, отправлять нечего
    """
    delivery = get_delivery_details(raw)

    base = {}
    for key, value in (
        ("shipping_address_city", delivery["city"]),
        ("shipping_address_region", delivery["region"]),
        ("shipping_address_zip", delivery["zip"]),
        ("shipping_address_country", delivery["country"]),
        # для відділення й поштомата адресу складу окремо не шлемо: вона
        # дублювала б точку видачі, keyCRM добудує її сама з warehouse_ref
        ("shipping_receive_point", delivery["pickup_point"]),
    ):
        if value:
            base[key] = value

    # Отримувача віддаємо тільки якщо він не замовник — так у документації
    if not parties["same"]:
        recipient = parties["recipient"]
        base["recipient_full_name"] = recipient["name"] or None
        base["recipient_phone"] = recipient["phone_e164"] or recipient["phone"] or None

    if not base:
        return [("empty", None)]

    with_service = {**base, "delivery_service_id": KEYCRM_DELIVERY_SERVICE_ID}
    variants: list[tuple[str, dict | None]] = []

    if delivery["warehouse_ref"]:
        variants.append(("warehouse", {**with_service, "warehouse_ref": delivery["warehouse_ref"]}))
    elif delivery["is_courier"]:
        address = delivery["courier_address"]
        # `shipping_address` — поле «Адрес» у діалозі доставки. В документації
        # його немає (тільки у відповіді API), тому за ним іде запасний варіант
        # через `shipping_secondary_line` — «Доп. адрес», який точно приймається
        variants.append(("courier", {**with_service, "shipping_address": address}))
        variants.append(("courier", {**with_service, "shipping_secondary_line": address}))
    else:
        if delivery["delivery_type"]:
            # ні складу, ні ознаки кур'єра — новий тип доставки, дивимось
            # у логах, які атрибути присилає Chekly
            logger.warning(
                "keyCRM: доставка типу %r без warehouse_ref, атрибути: %s",
                delivery["delivery_type"], delivery,
            )
        # прив'язувати нічого, але замовлення все одно їде Новою Поштою
        variants.append(("address", with_service))

    variants.append(("address", {**base, "shipping_service": DELIVERY_SERVICE}))
    variants.append(("none", None))
    return unique_by_body(variants)


def unique_by_body(variants: list[tuple[str, dict | None]]) -> list[tuple[str, dict | None]]:
    """Убирает варианты с одинаковым телом, сохраняя порядок и первый вид."""
    result: list[tuple[str, dict | None]] = []
    for kind, body in variants:
        if all(body != seen for _, seen in result):
            result.append((kind, body))
    return result


def _create_order_with_fallback(
    body: dict, shipping_variants: list[tuple[str, dict | None]]
) -> tuple[int, str, bool]:
    """Создаёт замовлення, отступая к более простому блоку доставки.

    Возвращает (id замовлення, вид доставки, пришлось ли отступать).

    Повторяем только на ошибках валидации (4xx) — при 5xx или обрыве сети
    замовлення могло создаться, и повтор сделал бы дубль.
    """
    last_response = None

    for attempt, (kind, shipping) in enumerate(shipping_variants):
        payload = {**body}
        if shipping:
            payload["shipping"] = shipping
        else:
            payload.pop("shipping", None)

        response = _session.post(f"{KEYCRM_BASE_URL}/order", json=payload, timeout=30)
        if response.ok:
            if attempt:
                logger.warning("keyCRM: замовлення створено з варіантом доставки %r", kind)
            return response.json()["id"], kind, bool(attempt)

        last_response = response
        if not 400 <= response.status_code < 500:
            break

        logger.warning(
            "keyCRM: варіант доставки %r відхилено (%s): %s",
            kind, response.status_code, response.text[:300],
        )

    last_response.raise_for_status()
    raise RuntimeError("keyCRM: не вдалося створити замовлення")


# ---------------------------------------------------------------------------
# Manager comment builder
# ---------------------------------------------------------------------------

def _format_manager_comment(raw: dict, tg_comment: str | None = None) -> str:
    parts = []

    order_number = raw.get("order_number") or (raw.get("name") or "").lstrip("#")
    parts.append(f"Замовлення №{order_number}")
    parts.append("")

    # Дата / оплата / замовник / доставка — тот же формат и порядок, что в PDF
    created_at = raw.get("created_at", "")
    parts.extend(render_header_text(build_header_blocks(raw, _format_date(created_at))))

    # Коментар покупця дублюємо в текст — щоб менеджер точно його побачив
    buyer_comment = get_buyer_comment(raw)
    if buyer_comment:
        parts.append("")
        parts.append("❗️ Коментар покупця:")
        parts.append(buyer_comment)

    line_items = raw.get("line_items") or []
    for item in line_items:
        parts.append("")
        title = item.get("title") or ""
        qty = item.get("quantity") or 1
        parts.append(title)
        parts.append(f"кількість х{qty}")
        parts.append("")
        variant_title = str(item.get("variant_title") or "").strip()
        if variant_title:
            parts.append(f"• Розмір: {variant_title}")
        for prop in item.get("properties") or []:
            name = (prop.get("name") or "").strip()
            value = (prop.get("value") or "").strip()
            if name and not name.startswith("_"):
                parts.append(f"• {name}: {value}")

    parts.append("")
    total = raw.get("total_price") or ""
    if total:
        parts.append(f"Сума замовлення - {total}")

    phones_section = _build_phones_section(line_items)
    if phones_section:
        parts.append("")
        parts.append(phones_section)

    if tg_comment and tg_comment.strip():
        parts.append("")
        parts.append("❗️❗️❗️")
        parts.append("")
        parts.append(tg_comment.strip())

    checkout_block = _build_checkout_block(raw)
    if checkout_block:
        parts.append("")
        parts.append(checkout_block)

    return "\n".join(parts)


def _build_checkout_block(raw: dict) -> str:
    """Хвост комментария под чертой: Checkout ID и фактическая оплата."""
    checkout_id = get_checkout_id(raw)
    if not checkout_id:
        return ""

    info = get_payment_info(raw)
    lines = [COMMENT_DIVIDER, f"Checkout ID: {checkout_id}"]

    if info["is_partial"] and info["paid"] is not None and info["total"] is not None:
        lines.append(
            f"Оплата: часткова — {info['paid']:.2f} з "
            f"{format_money(info['total'], info['currency'])}"
        )
    elif info["status"] == "paid" and info["paid"] is not None:
        lines.append(f"Оплата: повна — {format_money(info['paid'], info['currency'])}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phone formatting
# ---------------------------------------------------------------------------

def _is_phone_number(value: str) -> bool:
    """Returns True if value contains 9 or more digits."""
    return len(re.sub(r"\D", "", value)) >= 9


def _format_phone_dotted(phone_str: str) -> str:
    """Format Ukrainian phone as +38•XXX•XXX•XX•XX."""
    digits = re.sub(r"\D", "", phone_str)

    # Normalize to 10-digit local number (0XXXXXXXXX)
    if digits.startswith("380") and len(digits) >= 12:
        # +380XXXXXXXXX or 380XXXXXXXXX → remove '38', keep '0XXXXXXXXX'
        digits = digits[2:]
    elif digits.startswith("38") and len(digits) == 11:
        # 38XXXXXXXXX (missing leading 0 after +38) → prepend 0
        digits = "0" + digits[2:]
    elif digits.startswith("0") and len(digits) == 10:
        pass
    elif len(digits) == 9 and not digits.startswith("0"):
        # 9-digit number without leading 0 → prepend 0
        digits = "0" + digits

    if len(digits) == 10:
        return f"+38•{digits[0:3]}•{digits[3:6]}•{digits[6:8]}•{digits[8:10]}"

    # Fallback: just prepend +38
    return f"+38•{phone_str.strip()}"


def _get_phones_from_properties(properties: list) -> list:
    """Extract dotted-format phones from a single line item's properties."""
    phones = []
    for prop in properties or []:
        name = (prop.get("name") or "").lower().strip()
        value = (prop.get("value") or "").strip()
        if not value:
            continue
        if name in (_PROP_PHONE, _PROP_SECOND) and _is_phone_number(value):
            phones.append(_format_phone_dotted(value))
    return phones


def _build_phones_section(line_items: list) -> str:
    """Build the Телефони: section at the bottom of manager_comment."""
    items_with_phones = []
    for item in line_items or []:
        phones = _get_phones_from_properties(item.get("properties"))
        if phones:
            items_with_phones.append((item.get("title") or "", phones))

    if not items_with_phones:
        return ""

    lines = ["Телефони:"]
    for title, phones in items_with_phones:
        lines.append("")
        lines.append(f"{title}:")
        lines.extend(phones)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Date helper
# ---------------------------------------------------------------------------

def _format_date(created_at: str) -> str:
    """Convert ISO 8601 UTC timestamp to Kyiv time, formatted DD.MM.YYYY HH:MM."""
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        dt_kyiv = dt.astimezone(KYIV_TZ)
        return dt_kyiv.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return created_at
