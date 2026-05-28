import os
import re
import logging
from datetime import datetime

import pytz
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

KEYCRM_API_KEY = os.getenv("KEYCRM_API_KEY", "")
KEYCRM_SOURCE_ID = int(os.getenv("KEYCRM_SOURCE_ID", "2"))
KEYCRM_BASE_URL = "https://openapi.keycrm.app/v1"
KEYCRM_APP_URL = "https://timosh-design.keycrm.app/app/orders/view"

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


def create_crm_order(order) -> dict:
    """Create order in keyCRM. Returns {"id": int, "url": str}.
    Designed to run in a thread via asyncio.run_in_executor."""
    raw = order.raw_json or {}

    first_name = (order.customer_first_name or "").strip()
    last_name = (order.customer_last_name or "").strip()
    full_name = f"{first_name} {last_name}".strip() or "Без імені"
    email = raw.get("email") or None

    body = {
        "source_id": KEYCRM_SOURCE_ID,
        "source_uuid": str(order.order_number or order.id),
        "buyer": {
            "full_name": full_name,
            "phone": order.customer_phone_e164 or None,
            "email": email,
        },
        "manager_comment": _format_manager_comment(raw),
    }

    response = _session.post(f"{KEYCRM_BASE_URL}/order", json=body, timeout=30)
    response.raise_for_status()

    crm_id = response.json()["id"]
    return {"id": crm_id, "url": f"{KEYCRM_APP_URL}/{crm_id}"}


# ---------------------------------------------------------------------------
# Manager comment builder
# ---------------------------------------------------------------------------

def _format_manager_comment(raw: dict) -> str:
    parts = []

    order_number = raw.get("order_number") or (raw.get("name") or "").lstrip("#")
    parts.append(f"Замовлення №{order_number}")
    parts.append("")

    created_at = raw.get("created_at", "")
    if created_at:
        parts.append(f"Дата: {_format_date(created_at)}")

    shipping_lines = raw.get("shipping_lines") or []
    if shipping_lines:
        service = (shipping_lines[0].get("title") or "").strip()
        if service:
            parts.append(f"Доставка: {service}")

    shipping = raw.get("shipping_address") or {}
    if shipping:
        parts.append("Адреса доставки:")
        first = (shipping.get("first_name") or "").strip()
        last = (shipping.get("last_name") or "").strip()
        full = f"{first} {last}".strip()
        if full:
            parts.append(full)
        for field in ("address1", "address2", "city", "zip", "country", "province"):
            val = (shipping.get(field) or "").strip()
            if val:
                parts.append(val)
        phone = (shipping.get("phone") or "").strip()
        if phone:
            parts.append(phone)
        email = (raw.get("email") or "").strip()
        if email:
            parts.append(email)

    line_items = raw.get("line_items") or []
    for item in line_items:
        parts.append("")
        title = item.get("title") or ""
        qty = item.get("quantity") or 1
        parts.append(title)
        parts.append(f"кількість х{qty}")
        parts.append("")
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

    return "\n".join(parts)


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
