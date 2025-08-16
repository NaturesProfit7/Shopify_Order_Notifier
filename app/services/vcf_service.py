# services/vcf_service.py
from __future__ import annotations
from typing import Optional, Tuple

def _escape_vcard_text(value: str) -> str:
    if value is None:
        return ""
    out = value.replace("\\", "\\\\")
    out = out.replace("\n", "\\n").replace("\r", "")
    out = out.replace(",", "\\,").replace(";", "\\;")
    return out

def _join_crlf(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")

def build_contact_vcf(
    *,
    first_name: str = "",
    last_name: str = "",
    order_id: str,
    phone_e164: Optional[str] = None,
    embed_order_in_n: bool = True,   # <— ВАЖНО: для iOS включаем
) -> Tuple[bytes, str]:
    """
    vCard 3.0 (UTF-8, CRLF).
    По умолчанию embed_order_in_n=True — добавляем «— #order_id» в поле N (фамилия),
    чтобы iOS показывал номер заказа в шапке контакта.
    """
    # То, что хотим видеть как “полное имя”
    name_base = " ".join(x for x in [first_name or "", last_name or ""] if x).strip()
    fn_full = f"{name_base} — #{order_id}" if name_base else f"#{order_id}"

    # Готовим компоненты N: Фамилия;Имя;;;
    if embed_order_in_n:
        last_for_n = (last_name or "").strip()
        if last_for_n:
            last_for_n = f"{last_for_n} — #{order_id}"
        else:
            # если фамилии нет — положим #заказ в фамилию (чтобы точно отобразился)
            last_for_n = f"#{order_id}"
    else:
        last_for_n = last_name or ""

    n_last  = _escape_vcard_text(last_for_n)
    n_first = _escape_vcard_text(first_name or "")
    fn_full_escaped = _escape_vcard_text(fn_full)

    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{n_last};{n_first};;;",
        f"FN:{fn_full_escaped}",
    ]
    if phone_e164:
        lines.append(f"TEL;TYPE=CELL:{phone_e164}")
    # Дополнительно можно оставить заметку:
    lines.append(f"NOTE:{_escape_vcard_text('Замовлення #' + str(order_id))}")
    lines.append("END:VCARD")

    return _join_crlf(lines), f"contact_#{order_id}.vcf"
