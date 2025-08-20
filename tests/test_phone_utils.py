# tests/test_phone_utils.py
from app.services.phone_utils import normalize_ua_phone, pretty_ua_phone

def test_normalize_e164_ok():
    assert normalize_ua_phone("+380672326239") == "+380672326239"
    assert normalize_ua_phone("380672326239") == "+380672326239"

def test_normalize_local_ok():
    assert normalize_ua_phone("0672326239") == "+380672326239"
    assert normalize_ua_phone("(067) 232-62-39") == "+380672326239"

def test_normalize_bad():
    assert normalize_ua_phone("12345") is None
    assert normalize_ua_phone("") is None
    assert normalize_ua_phone(None) is None

def test_pretty_format():
    assert pretty_ua_phone("+380672326239") == "+380672326239"
    # не-ua или неверный формат — вернуть как есть
    assert pretty_ua_phone("+48123123123") == "+48123123123"
    assert pretty_ua_phone("not-a-number") == "not-a-number"
