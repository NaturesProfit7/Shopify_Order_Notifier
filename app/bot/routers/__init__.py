from . import commands
from . import navigation
from . import orders
from . import management
from . import test_commands
from . import webhook  # НОВЫЙ роутер

__all__ = [
    'commands',
    'navigation',
    'orders',
    'management',
    'test_commands',
    'webhook'  # Добавлен
]