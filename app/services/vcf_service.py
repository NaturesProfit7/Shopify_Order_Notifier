from __future__ import annotations
from typing import Optional, Tuple


def _escape_vcard_text(value: str) -> str:
    """
    Экранирует спецсимволы согласно vCard 3.0:
      - Запятая -> \\,
      - Точка с запятой -> \\;
      - Обратный слэш -> \\\\
      - Переводы строк -> \\n
    """
    if value is None:
        return ""
    out = value.replace("\\", "\\\\")
    out = out.replace("\n", "\\n").replace("\r", "")
    out = out.replace(",", "\\,").replace(";", "\\;")
    return out


def _join_crlf(lines: list[str]) -> bytes:
    """Собирает файл с CRLF как требует vCard."""
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def build_contact_vcf(
    *,
    first_name: str = "",
    last_name: str = "",
    order_id: str,
    phone_e164: Optional[str] = None,
) -> Tuple[bytes, str]:
    """
    Формирует vCard 3.0 (UTF-8, CRLF) с:
      FN: Имя Фамилия — #order_id
      N:  Фамилия;Имя;;;
      TEL: +380XXXXXXXXX (если есть)
    """
    fn_name_part = " ".join(x for x in [first_name or "", last_name or ""] if x).strip()
    fn_full = f"{fn_name_part} — #{order_id}" if fn_name_part else f"#{order_id}"

    n_last = _escape_vcard_text(last_name or "")
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
    lines.append("END:VCARD")

    vcf_bytes = _join_crlf(lines)
    filename = f"contact_#{order_id}.vcf"
    return vcf_bytes, filename
