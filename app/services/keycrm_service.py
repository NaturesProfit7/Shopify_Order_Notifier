import os
import re
import logging
from datetime import datetime, timedelta

import pytz
import requests
from urllib.parse import urljoin
from dotenv import load_dotenv

from app.services.order_fields import (
    DELIVERY_SERVICE,
    build_header_blocks,
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

# «Еквайринг» в справочнике методов оплаты keyCRM (GET /order/payment-method)
KEYCRM_PAYMENT_METHOD_ID = int(os.getenv("KEYCRM_PAYMENT_METHOD_ID", "7"))

# Поиск внешней транзакции: checkout id лежит в description транзакции
# («44411110******61 <checkout id>»), поэтому фильтра по нему в API нет —
# перебираем непривязанные транзакции за окно вокруг даты заказа.
TRANSACTION_SEARCH_PAGES = 20
TRANSACTION_SEARCH_LIMIT = 50
TRANSACTION_SEARCH_DAYS_BEFORE = 3
TRANSACTION_SEARCH_DAYS_AFTER = 1

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

    # Покупець у CRM — замовник. Якщо посилку отримує інша людина, віддаємо її
    # окремо: keyCRM підставляє ці поля в ТТН
    if not parties["same"]:
        recipient = parties["recipient"]
        body["shipping"] = {
            "shipping_service": DELIVERY_SERVICE,
            "recipient_full_name": recipient["name"] or None,
            "recipient_phone": recipient["phone_e164"] or recipient["phone"] or None,
        }

    response = _session.post(f"{KEYCRM_BASE_URL}/order", json=body, timeout=30)
    response.raise_for_status()

    crm_id = response.json()["id"]
    return {"id": crm_id, "url": f"{KEYCRM_APP_URL}/{crm_id}"}


# ---------------------------------------------------------------------------
# Привязка оплаты Chekly к замовленню в keyCRM
# ---------------------------------------------------------------------------

def _parse_crm_datetime(value: str | None) -> datetime | None:
    """'2026-09-05T19:40:29.000000Z' → aware datetime (UTC)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _transaction_matches(transaction: dict, checkout_id: str) -> bool:
    """Транзакция относится к нашему заказу, если checkout id встречается
    в её описании (там keyCRM хранит «маска картки + checkout id») либо
    в одном из идентификаторов."""
    needle = checkout_id.lower()
    for field in ("description", "source_uuid", "uuid"):
        value = transaction.get(field)
        if value and needle in str(value).lower():
            return True
    return False


def find_external_transaction(checkout_id: str, order_created_at: str | None = None) -> dict | None:
    """Ищет внешнюю транзакцию keyCRM по checkout id платёжки.

    Фильтра по описанию в API нет, поэтому перебираем непривязанные
    транзакции (свежие идут первыми) и останавливаемся, когда ушли по дате
    заведомо раньше заказа.

    Designed to run in a thread via asyncio.run_in_executor.
    """
    if not checkout_id:
        return None

    # Дешёвая попытка: вдруг платёжный сервис положил checkout id в uuid
    response = _session.get(
        f"{KEYCRM_BASE_URL}/payments/external-transactions",
        params={"filter[transaction_uuid]": checkout_id, "limit": 1},
        timeout=30,
    )
    response.raise_for_status()
    exact = response.json().get("data") or []
    if exact:
        return exact[0]

    created_at = _parse_crm_datetime(order_created_at)
    cutoff = created_at - timedelta(days=TRANSACTION_SEARCH_DAYS_BEFORE) if created_at else None
    seen_recent = cutoff is None

    for page in range(1, TRANSACTION_SEARCH_PAGES + 1):
        response = _session.get(
            f"{KEYCRM_BASE_URL}/payments/external-transactions",
            params={
                "filter[is_attached]": "false",
                "limit": TRANSACTION_SEARCH_LIMIT,
                "page": page,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        transactions = payload.get("data") or []
        if not transactions:
            return None

        page_has_recent = False
        for transaction in transactions:
            if _transaction_matches(transaction, checkout_id):
                return transaction

            transaction_date = _parse_crm_datetime(transaction.get("transaction_date"))
            if cutoff is None or transaction_date is None or transaction_date >= cutoff:
                page_has_recent = True

        seen_recent = seen_recent or page_has_recent
        # список идёт от свежих к старым: как только целая страница оказалась
        # старше окна поиска — дальше искать бессмысленно
        if seen_recent and not page_has_recent:
            return None
        if not payload.get("next_page_url"):
            return None

    logger.warning("keyCRM: transaction for checkout %s not found in %s pages",
                   checkout_id, TRANSACTION_SEARCH_PAGES)
    return None


def _post_json(url: str, body: dict) -> dict:
    """POST в keyCRM, устойчивый к редиректам.

    При 301/302/303 requests меняет метод на GET и повторяет запрос — keyCRM
    в ответ говорит «The GET method is not supported… Supported methods: POST».
    Поэтому редиректы не отдаём библиотеке, а повторяем POST сами.
    """
    response = _session.post(url, json=body, timeout=30, allow_redirects=False)

    for _ in range(3):
        if not response.is_redirect:
            break
        location = response.headers.get("Location")
        if not location:
            break
        url = urljoin(url, location)
        logger.info("keyCRM: redirect on POST, repeating as POST to %s", url)
        response = _session.post(url, json=body, timeout=30, allow_redirects=False)

    if not response.ok:
        # тело ответа keyCRM объясняет причину гораздо лучше, чем статус
        raise requests.HTTPError(
            f"{response.status_code} {response.reason} for {url}: {response.text[:500]}",
            response=response,
        )

    return response.json()


def create_order_payment(crm_order_id: int, amount: float, description: str | None = None,
                         payment_date: str | None = None) -> dict:
    """Создаёт оплату у замовлення в keyCRM. Возвращает объект оплаты."""
    body = {
        "payment_method_id": KEYCRM_PAYMENT_METHOD_ID,
        "amount": amount,
        "status": "paid",
    }
    if description:
        body["description"] = description
    if payment_date:
        body["payment_date"] = payment_date

    return _post_json(f"{KEYCRM_BASE_URL}/order/{crm_order_id}/payment", body)


def attach_transaction_to_payment(payment_id: int, transaction: dict) -> None:
    """Прикрепляет внешнюю транзакцию к созданной оплате."""
    body = {"transaction_id": transaction["id"]}
    if transaction.get("uuid"):
        body["transaction_uuid"] = str(transaction["uuid"])

    _post_json(f"{KEYCRM_BASE_URL}/payments/{payment_id}/external-transactions", body)


def attach_payment_to_crm_order(order, crm_order_id: int) -> dict:
    """Привязывает оплату Chekly к созданному замовленню keyCRM.

    Оплату создаём только если транзакция нашлась — иначе менеджер
    привязывает её руками, а бот пишет об этом в Telegram.

    Возвращает {"status": ...} со значениями:
        attached              — оплата создана и привязана
        no_checkout_id        — заказ не из Chekly
        no_amount             — Shopify не отдал сумму оплаты
        transaction_not_found — транзакции с таким checkout id нет в CRM

    Designed to run in a thread via asyncio.run_in_executor.
    """
    raw = order.raw_json or {}

    checkout_id = get_checkout_id(raw)
    if not checkout_id:
        return {"status": "no_checkout_id"}

    info = get_payment_info(raw)
    amount = info["paid"]
    if not amount or amount <= 0:
        return {"status": "no_amount", "checkout_id": checkout_id}

    transaction = find_external_transaction(checkout_id, raw.get("created_at"))
    if not transaction:
        return {
            "status": "transaction_not_found",
            "checkout_id": checkout_id,
            "amount": amount,
            "is_partial": info["is_partial"],
        }

    description = f"Chekly {checkout_id}"
    if info["is_partial"]:
        description = f"Часткова оплата • {description}"

    payment = create_order_payment(
        crm_order_id,
        amount=amount,
        description=description,
        payment_date=_format_payment_date(transaction.get("transaction_date")),
    )
    attach_transaction_to_payment(payment["id"], transaction)

    return {
        "status": "attached",
        "checkout_id": checkout_id,
        "amount": amount,
        "currency": info["currency"],
        "is_partial": info["is_partial"],
        "payment_id": payment["id"],
        "transaction_id": transaction["id"],
    }


def _format_payment_date(transaction_date: str | None) -> str | None:
    """UTC-дата транзакции → 'YYYY-MM-DD HH:MM:SS' по Киеву."""
    parsed = _parse_crm_datetime(transaction_date)
    if not parsed:
        return None
    return parsed.astimezone(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S")


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
        parts.append("Коментар покупця:")
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
