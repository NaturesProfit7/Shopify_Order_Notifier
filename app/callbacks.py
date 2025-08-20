from __future__ import annotations

from typing import Tuple, Dict


def route_callback(data: str) -> Tuple[str | None, Dict[str, object]]:
    """Parse callback_data into action and params."""
    parts = (data or "").split(":")
    if not parts or parts[0] == "":
        return None, {}

    try:
        if parts[0] == "order":
            order_id = int(parts[1])
            if len(parts) == 4 and parts[2] == "set":
                return "order_set", {"order_id": order_id, "status": parts[3]}
            if len(parts) == 3 and parts[2] == "view":
                return "order_view", {"order_id": order_id}
            if len(parts) == 4 and parts[2] == "resend" and parts[3] in {"pdf", "vcf"}:
                return "order_resend", {"order_id": order_id, "format": parts[3]}
        elif parts[0] == "orders" and len(parts) >= 4 and parts[1] == "list":
            kind = parts[2]
            if parts[3].startswith("offset="):
                offset = int(parts[3].split("=", 1)[1])
            else:
                offset = 0
            return "orders_list", {"kind": kind, "offset": offset}
    except Exception:
        return None, {}

    return None, {}

