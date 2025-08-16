from __future__ import annotations
import re
from typing import Optional

UA_COUNTRY = "380"


def _only_digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def normalize_ua_phone(phone_raw: str | None) -> Optional[str]:
    """
    Преобразует входной номер в формат +380XXXXXXXXX.
    Возвращает None, если нормализовать не удалось.
    """
    digits = _only_digits(phone_raw)
    if not digits:
        return None

    if digits.startswith(UA_COUNTRY) and len(digits) == 12:
        return f"+{digits}"

    if digits.startswith("0") and len(digits) == 10:
        return f"+{UA_COUNTRY}{digits[1:]}"

    if len(digits) == 12 and digits.startswith(UA_COUNTRY):
        return f"+{digits}"

    return None


def pretty_ua_phone(e164: str) -> str:
    """
    Делает вид +38•0XX•XXX•XX•XX для украинских номеров.
    Если формат не совпадает с E.164, вернёт как есть.
    """
    if not (isinstance(e164, str) and e164.startswith("+") and len(e164) == 13 and e164[1:].isdigit()):
        return e164
    if not e164.startswith("+380"):
        return e164

    tail = e164[4:]
    if len(tail) != 9 or not tail.isdigit():
        return e164

    return f"+38•0{tail[0:2]}•{tail[2:5]}•{tail[5:7]}•{tail[7:9]}"
