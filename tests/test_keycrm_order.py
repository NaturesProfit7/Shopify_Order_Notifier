# tests/test_keycrm_order.py
"""Создание замовлення в keyCRM: покупець і отримувач."""
from types import SimpleNamespace

import pytest

from app.services import keycrm_service as crm
from app.services.order_fields import get_order_contact
from tests.fixtures.chekly_orders import order


class _Response:
    is_redirect = False
    ok = True
    status_code = 200
    reason = "OK"
    headers: dict = {}
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _SessionStub:
    """Подменяет requests.Session и запоминает, что ушло в keyCRM."""

    def __init__(self):
        self.post_calls = []

    def post(self, url, json=None, timeout=None, allow_redirects=True):
        self.post_calls.append((url, json or {}))
        return _Response({"id": 1000})


@pytest.fixture
def session(monkeypatch):
    stub = _SessionStub()
    monkeypatch.setattr(crm, "_session", stub)
    return stub


def test_crm_order_sends_customer_as_buyer_and_recipient_separately(session):
    raw = order("PAID_DIFFERENT_PEOPLE")
    first_name, last_name, phone = get_order_contact(raw)
    crm.create_crm_order(SimpleNamespace(
        id=1, order_number="4582", comment=None, raw_json=raw,
        customer_first_name=first_name, customer_last_name=last_name,
        customer_phone_e164=phone,
    ))

    _, body = session.post_calls[0]
    assert body["buyer"] == {
        "full_name": "Тестовий Замовник",
        "phone": "+380931112255",
        "email": "buyer@example.com",
    }
    assert body["shipping"] == {
        "shipping_service": "Нова Пошта",
        "recipient_full_name": "Тестовий Отримувач",
        "recipient_phone": "+380931112244",
    }


def test_crm_order_has_no_shipping_block_for_a_single_person(session):
    raw = order("PARTIAL_SAME_PERSON")
    first_name, last_name, phone = get_order_contact(raw)
    crm.create_crm_order(SimpleNamespace(
        id=1, order_number="4580", comment=None, raw_json=raw,
        customer_first_name=first_name, customer_last_name=last_name,
        customer_phone_e164=phone,
    ))

    _, body = session.post_calls[0]
    assert "shipping" not in body
    assert body["buyer"]["full_name"] == "Олена Тестова"
