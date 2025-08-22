# app/services/address_utils.py
from __future__ import annotations
from typing import Tuple, Dict, Any, Optional


def normalize_address_field(value: str) -> str:
    """Нормализация поля адреса для сравнения"""
    if not value:
        return ""
    return str(value).strip().lower()


def addresses_are_same(shipping: Dict[str, Any], billing: Dict[str, Any]) -> bool:
    """
    Проверяет, одинаковые ли адреса доставки и оплаты.
    Сравниваем ключевые поля: имя, адрес, город, индекс.
    """
    if not shipping or not billing:
        return False

    # Сравниваем ключевые поля
    fields_to_compare = ['first_name', 'last_name', 'address1', 'city', 'zip']

    for field in fields_to_compare:
        shipping_val = normalize_address_field(shipping.get(field, ''))
        billing_val = normalize_address_field(billing.get(field, ''))

        if shipping_val != billing_val:
            return False

    return True


def get_delivery_and_contact_info(order: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Возвращает (delivery_address, contact_info) в зависимости от сценария:

    Если адреса одинаковые:
    - delivery_address = shipping_address
    - contact_info = shipping_address

    Если адреса разные:
    - delivery_address = billing_address (кому доставляем)
    - contact_info = shipping_address (с кем связываемся)
    """
    shipping = order.get('shipping_address', {})
    billing = order.get('billing_address', {})

    # Если нет billing адреса - используем shipping
    if not billing:
        return shipping, shipping

    # Если нет shipping адреса - используем billing
    if not shipping:
        return billing, billing

    # Если адреса одинаковые
    if addresses_are_same(shipping, billing):
        return shipping, shipping

    # Если адреса разные - billing для доставки, shipping для контакта
    return billing, shipping


def build_delivery_address_text(delivery_address: Dict[str, Any]) -> str:
    """
    Строит текст адреса доставки для PDF.
    """
    if not delivery_address:
        return "—"

    lines = []

    # ФИО получателя
    first_name = (delivery_address.get('first_name') or '').strip()
    last_name = (delivery_address.get('last_name') or '').strip()
    full_name = f"{first_name} {last_name}".strip()

    if full_name:
        lines.append(full_name)

    # Адрес
    for field in ['address1', 'address2', 'city', 'zip', 'country']:
        value = (delivery_address.get(field) or '').strip()
        if value:
            lines.append(value)

    # Телефон получателя (если есть)
    phone = (delivery_address.get('phone') or '').strip()
    if phone:
        from app.services.phone_utils import normalize_ua_phone, pretty_ua_phone
        phone_e164 = normalize_ua_phone(phone)
        if phone_e164:
            lines.append(pretty_ua_phone(phone_e164))
        else:
            lines.append(phone)

    return '\n'.join(lines) if lines else "—"


def get_contact_phone_e164(contact_info: Dict[str, Any]) -> Optional[str]:
    """
    Извлекает и нормализует телефон для контакта (VCF).
    """
    phone_raw = (contact_info.get('phone') or '').strip()
    if not phone_raw:
        return None

    from app.services.phone_utils import normalize_ua_phone
    return normalize_ua_phone(phone_raw)


def get_contact_name(contact_info: Dict[str, Any]) -> Tuple[str, str]:
    """
    Извлекает имя и фамилию для контакта (VCF).
    """
    first_name = (contact_info.get('first_name') or '').strip()
    last_name = (contact_info.get('last_name') or '').strip()
    return first_name, last_name