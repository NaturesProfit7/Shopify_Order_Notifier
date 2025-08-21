# app/bot/routers/__init__.py - ОБНОВЛЕННЫЙ
"""Модули роутеров бота"""

from . import commands
from . import navigation

# Пока что используем только эти два модуля
# TODO: Добавить orders.py и management.py когда перенесем остальной код

__all__ = [
    'commands',
    'navigation'
]