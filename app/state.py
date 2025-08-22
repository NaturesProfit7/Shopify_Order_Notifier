# app/state.py - С ИСПРАВЛЕННОЙ ЛОГИКОЙ АДРЕСОВ
"""
Работа с идемпотентностью через PostgreSQL.
Использует таблицу orders для хранения обработанных заказов.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime
from sqlalchemy.exc import IntegrityError
from app.db import get_session
from app.models import Order, OrderStatus


async def is_processed(order_id: str | int) -> bool:
    """
    Проверяет, был ли заказ уже обработан.
    Возвращает True, если запись с таким id существует и is_processed=True.
    """
    oid = int(order_id)

    with get_session() as session:
        order = session.query(Order).filter(Order.id == oid).first()
        return order is not None and order.is_processed


async def mark_processed(order_id: str | int, order_data: Optional[dict] = None) -> bool:
    """
    Помечает заказ как обработанный.
    Если записи нет - создает новую.
    Если запись есть - обновляет is_processed=True.

    Args:
        order_id: ID заказа из Shopify
        order_data: Полные данные заказа (опционально, для сохранения в raw_json)

    Returns:
        True если успешно, False если уже был обработан
    """
    oid = int(order_id)

    with get_session() as session:
        # Проверяем существующую запись
        order = session.query(Order).filter(Order.id == oid).first()

        if order:
            if order.is_processed:
                return False  # Уже обработан

            # Обновляем существующую запись
            order.is_processed = True
            order.updated_at = datetime.utcnow()
            if order_data:
                order.raw_json = order_data
                # Обновляем поля из данных заказа
                _update_order_fields(order, order_data)
        else:
            # Создаем новую запись
            order = Order(
                id=oid,
                is_processed=True,
                status=OrderStatus.NEW,
                raw_json=order_data
            )

            if order_data:
                _update_order_fields(order, order_data)

            session.add(order)

        try:
            session.commit()
            return True
        except IntegrityError:
            # Race condition - другой процесс уже создал запись
            session.rollback()
            return False


def _update_order_fields(order: Order, data: dict) -> None:
    """
    Обновляет поля заказа из данных Shopify с НОВОЙ ЛОГИКОЙ АДРЕСОВ.
    """
    # Номер заказа
    order.order_number = str(data.get("order_number") or data.get("id") or "")

    # НОВАЯ ЛОГИКА: используем исправленную функцию извлечения контактных данных
    from app.services.address_utils import get_delivery_and_contact_info, get_contact_name, get_contact_phone_e164

    # Получаем контактную информацию с учетом логики адресов
    _, contact_info = get_delivery_and_contact_info(data)

    # Извлекаем имя и фамилию контактного лица
    contact_first_name, contact_last_name = get_contact_name(contact_info)

    # Если в контактной информации нет имени - пробуем customer как fallback
    if not contact_first_name and not contact_last_name:
        customer = data.get("customer") or {}
        contact_first_name = (customer.get("first_name") or "").strip()
        contact_last_name = (customer.get("last_name") or "").strip()

    # Сохраняем контактные данные в заказ
    order.customer_first_name = (contact_first_name or "")[:100]
    order.customer_last_name = (contact_last_name or "")[:100]

    # Извлекаем телефон контактного лица
    phone_e164 = get_contact_phone_e164(contact_info)

    # Если в контактной информации нет телефона - пробуем другие источники
    if not phone_e164:
        from app.services.phone_utils import normalize_ua_phone

        customer = data.get("customer") or {}
        default_addr = customer.get("default_address") or {}

        # Проверяем различные источники телефона
        for phone_source in [
            customer.get("phone"),
            data.get("phone"),
            default_addr.get("phone"),
        ]:
            if phone_source and str(phone_source).strip():
                phone_e164 = normalize_ua_phone(str(phone_source).strip())
                if phone_e164:
                    break

    if phone_e164:
        order.customer_phone_e164 = phone_e164[:32]


async def get_order_by_id(order_id: str | int) -> Optional[Order]:
    """
    Получает запись заказа из БД по ID.
    """
    oid = int(order_id)

    with get_session() as session:
        return session.query(Order).filter(Order.id == oid).first()


async def update_telegram_info(
        order_id: str | int,
        chat_id: str = None,
        message_id: int = None
) -> bool:
    """
    Обновляет информацию о Telegram-сообщениях для заказа.
    Используется когда отправляем сообщения с кнопками.
    """
    oid = int(order_id)

    with get_session() as session:
        order = session.query(Order).filter(Order.id == oid).first()
        if not order:
            return False

        if chat_id:
            order.chat_id = str(chat_id)[:64]
        if message_id:
            order.last_message_id = message_id

        order.updated_at = datetime.utcnow()
        session.commit()
        return True


# Для совместимости с тестами
async def clear_processed() -> None:
    """
    Очищает флаги is_processed у всех заказов (для тестов).
    НЕ ИСПОЛЬЗОВАТЬ В PRODUCTION!
    """
    with get_session() as session:
        session.query(Order).update({"is_processed": False})
        session.commit()