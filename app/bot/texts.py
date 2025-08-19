from app.models import OrderStatus
from app.services.message_templates import render_simple_confirm
from app.services.status_ui import status_title

def build_manager_message(order_json: dict, status: OrderStatus) -> str:
    header = f"Статус: {status_title(status)}"
    return f"{header}\n\n{render_simple_confirm(order_json)}"
