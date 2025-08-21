# app/bot/routers/shared/state.py
"""Общие состояния и хранилища данных бота"""

from typing import Dict, Set

# Хранилище для отслеживания сообщений каждого пользователя
user_navigation_messages: Dict[int, int] = {}  # user_id -> message_id
user_order_files: Dict[int, Dict[int, Set[int]]] = {}  # user_id -> {order_id -> {message_ids}}


def get_navigation_message_id(user_id: int) -> int | None:
    """Получить ID навигационного сообщения пользователя"""
    return user_navigation_messages.get(user_id)


def set_navigation_message_id(user_id: int, message_id: int) -> None:
    """Установить ID навигационного сообщения пользователя"""
    user_navigation_messages[user_id] = message_id


def remove_navigation_message_id(user_id: int) -> None:
    """Удалить ID навигационного сообщения пользователя"""
    if user_id in user_navigation_messages:
        del user_navigation_messages[user_id]


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