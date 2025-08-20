# app/state.py
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
    Обновляет поля заказа из данных Shopify.
    """
    # Номер заказа
    order.order_number = str(data.get("order_number") or data.get("id") or "")

    # Данные клиента
    customer = data.get("customer") or {}
    shipping = data.get("shipping_address") or {}
    billing = data.get("billing_address") or {}

    # Извлекаем имя и фамилию (приоритет: customer -> shipping -> billing)
    order.customer_first_name = (
                                        customer.get("first_name")
                                        or shipping.get("first_name")
                                        or billing.get("first_name")
                                        or ""
                                )[:100]  # Ограничиваем длину по схеме БД

    order.customer_last_name = (
                                       customer.get("last_name")
                                       or shipping.get("last_name")
                                       or billing.get("last_name")
                                       or ""
                               )[:100]

    # Извлекаем телефон (используем вашу функцию нормализации)
    from app.services.phone_utils import normalize_ua_phone

    phone_raw = (
            customer.get("phone")
            or data.get("phone")
            or shipping.get("phone")
            or billing.get("phone")
            or ""
    )

    if phone_raw:
        phone_e164 = normalize_ua_phone(phone_raw)
        if phone_e164:
            order.customer_phone_e164 = phone_e164[:32]  # Ограничиваем длину


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