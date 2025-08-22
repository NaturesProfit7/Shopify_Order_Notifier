# app/bot/routers/shared/state.py - С ТРЕКИНГОМ WEBHOOK СООБЩЕНИЙ
"""Общие состояния и хранилища данных бота"""

from typing import Dict, Set

# Хранилище для отслеживания сообщений каждого пользователя
user_navigation_messages: Dict[int, int] = {}  # user_id -> message_id (последнее меню)
user_order_files: Dict[int, Dict[int, Set[int]]] = {}  # user_id -> {order_id -> {message_ids}}

# Отслеживание ВСЕХ навигационных сообщений пользователя
user_all_navigation_messages: Dict[int, Set[int]] = {}  # user_id -> {message_ids}

# НОВОЕ: Трекинг WEBHOOK сообщений заказов
webhook_order_messages: Dict[int, Set[int]] = {}  # order_id -> {message_ids}


def get_navigation_message_id(user_id: int) -> int | None:
    """Получить ID последнего навигационного сообщения пользователя"""
    return user_navigation_messages.get(user_id)


def set_navigation_message_id(user_id: int, message_id: int) -> None:
    """Установить ID последнего навигационного сообщения пользователя"""
    user_navigation_messages[user_id] = message_id


def remove_navigation_message_id(user_id: int) -> None:
    """Удалить ID последнего навигационного сообщения пользователя"""
    if user_id in user_navigation_messages:
        del user_navigation_messages[user_id]


# Функции для отслеживания ВСЕХ навигационных сообщений

def add_navigation_message(user_id: int, message_id: int) -> None:
    """Добавить ID навигационного сообщения в отслеживание"""
    if user_id not in user_all_navigation_messages:
        user_all_navigation_messages[user_id] = set()
    user_all_navigation_messages[user_id].add(message_id)


def get_all_navigation_messages(user_id: int) -> Set[int]:
    """Получить все ID навигационных сообщений пользователя"""
    return user_all_navigation_messages.get(user_id, set()).copy()


def clear_all_navigation_messages(user_id: int) -> None:
    """Очистить все отслеживаемые навигационные сообщения пользователя"""
    if user_id in user_all_navigation_messages:
        user_all_navigation_messages[user_id].clear()
    if user_id in user_navigation_messages:
        del user_navigation_messages[user_id]


def remove_navigation_message(user_id: int, message_id: int) -> None:
    """Удалить конкретное навигационное сообщение из отслеживания"""
    if user_id in user_all_navigation_messages:
        user_all_navigation_messages[user_id].discard(message_id)
    if user_navigation_messages.get(user_id) == message_id:
        del user_navigation_messages[user_id]


# НОВЫЕ функции для WEBHOOK сообщений

def add_webhook_message(order_id: int, message_id: int) -> None:
    """Добавить ID сообщения webhook заказа"""
    if order_id not in webhook_order_messages:
        webhook_order_messages[order_id] = set()
    webhook_order_messages[order_id].add(message_id)


def get_webhook_messages(order_id: int) -> Set[int]:
    """Получить все ID webhook сообщений заказа"""
    return webhook_order_messages.get(order_id, set()).copy()


def clear_webhook_messages(order_id: int) -> None:
    """Очистить все webhook сообщения заказа"""
    if order_id in webhook_order_messages:
        webhook_order_messages[order_id].clear()


def is_webhook_message(message_id: int) -> bool:
    """Проверить, является ли сообщение webhook сообщением"""
    for order_id, message_ids in webhook_order_messages.items():
        if message_id in message_ids:
            return True
    return False


def get_order_by_webhook_message(message_id: int) -> int | None:
    """Получить order_id по ID webhook сообщения"""
    for order_id, message_ids in webhook_order_messages.items():
        if message_id in message_ids:
            return order_id
    return None


# Существующие функции для файлов заказов

def add_order_file_message(user_id: int, order_id: int, message_id: int) -> None:
    """Добавить ID файлового сообщения заказа"""
    if user_id not in user_order_files:
        user_order_files[user_id] = {}
    if order_id not in user_order_files[user_id]:
        user_order_files[user_id][order_id] = set()
    user_order_files[user_id][order_id].add(message_id)


def get_order_file_messages(user_id: int, order_id: int) -> Set[int]:
    """Получить ID всех файловых сообщений заказа"""
    if user_id in user_order_files and order_id in user_order_files[user_id]:
        return user_order_files[user_id][order_id].copy()
    return set()


def clear_order_file_messages(user_id: int, order_id: int) -> None:
    """Очистить файловые сообщения заказа"""
    if user_id in user_order_files and order_id in user_order_files[user_id]:
        user_order_files[user_id][order_id].clear()


def clear_all_user_files(user_id: int) -> Dict[int, Set[int]]:
    """Очистить все файлы пользователя и вернуть их для удаления"""
    if user_id in user_order_files:
        files_to_delete = user_order_files[user_id].copy()
        user_order_files[user_id].clear()
        return files_to_delete
    return {}