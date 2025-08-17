from __future__ import annotations
import re
from typing import Optional

UA_COUNTRY = "380"

# --- helpers ---------------------------------------------------------------

_SPLIT_PAT = re.compile(r"[;/,\|\n]")  # разделители нескольких номеров

_EXT_PAT = re.compile(
    r"(\s*(доб\.?|ext\.?|ext|доб|x|#)\s*\d+)$",
    flags=re.IGNORECASE
)

def _only_digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")

def _strip_extension(s: str) -> str:
    """Срезает 'доб.123', 'ext 45', 'x99' в конце строки."""
    return _EXT_PAT.sub("", s or "").strip()

def _first_chunk(s: str) -> str:
    """Берём первый фрагмент, если в строке несколько номеров."""
    parts = [p.strip() for p in _SPLIT_PAT.split(s or "") if p.strip()]
    return parts[0] if parts else (s or "")

# --- public API ------------------------------------------------------------

def normalize_ua_phone(phone_raw: str | None) -> Optional[str]:
    """
    Преобразует входной номер к E.164 формату: +380XXXXXXXXX.
    Возвращает None, если привести нельзя.
    """
    if not phone_raw:
        return None

    cleaned = _strip_extension(_first_chunk(phone_raw))
    digits = _only_digits(cleaned)
    if not digits:
        return None

    if digits.startswith("00380") and len(digits) >= 14:
        digits = digits[2:]  # срезаем '00' -> '380...'

    if len(digits) == 12 and digits.startswith(UA_COUNTRY):
        return f"+{digits}"

    if len(digits) == 10 and digits.startswith("0"):
        return f"+{UA_COUNTRY}{digits[1:]}"

    return None


def pretty_ua_phone(e164: str) -> str:
    """
    Возвращает украинский номер как есть (+380XXXXXXXXX), без разделителей.
    Если строка не E.164, вернёт её как есть.
    """
    if not (isinstance(e164, str) and e164.startswith("+") and len(e164) == 13 and e164[1:].isdigit()):
        return e164
    return e164
