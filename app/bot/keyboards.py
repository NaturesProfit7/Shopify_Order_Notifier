from app.models import OrderStatus
from app.services.status_ui import buttons_for_status

def build_inline_keyboard(status: OrderStatus, order_id: int):
    """Возвращает готовый inline_keyboard (list[list[dict]]) — совместимо с твоим tg_service."""
    return buttons_for_status(status, order_id)
