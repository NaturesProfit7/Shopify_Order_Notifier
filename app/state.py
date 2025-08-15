# app/state.py
"""
Временное in‑memory хранилище для идемпотентности.
Хранит обработанные order_id в наборе (_processed_orders).
Заменим на БД на шаге 8.
"""

import asyncio
from typing import Set

# Глобальное множество обработанных заказов (в памяти процесса)
_processed_orders: Set[str] = set()

# Замок для атомарных проверок/записей в асинхронной среде
_lock = asyncio.Lock()


async def is_processed(order_id: str | int) -> bool:
    """
    Возвращает True, если order_id уже отмечен как обработанный.
    Принимает str или int, внутри всегда приводит к str.
    """
    oid = str(order_id)
    async with _lock:
        return oid in _processed_orders


async def mark_processed(order_id: str | int) -> None:
    """
    Помечает order_id как обработанный (добавляет в набор).
    """
    oid = str(order_id)
    async with _lock:
        _processed_orders.add(oid)


# Вспомогательная функция для локальных тестов
async def clear_processed() -> None:
    """
    Очищает хранилище обработанных заказов (удобно для тестов).
    """
    async with _lock:
        _processed_orders.clear()
