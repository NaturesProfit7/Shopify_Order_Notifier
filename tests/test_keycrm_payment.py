# tests/test_keycrm_payment.py
"""Привязка оплаты Chekly к замовленню в keyCRM."""
from types import SimpleNamespace

import pytest

from app.services import keycrm_service as crm
from tests.fixtures.chekly_orders import order

CHECKOUT_ID = "e092a38a-3327-4ec2-a24d-0bacca9c97d9"


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _SessionStub:
    """Подменяет requests.Session: отдаёт заготовленные страницы транзакций."""

    def __init__(self, pages=None, exact=None):
        self.pages = pages or []
        self.exact = exact or []
        self.get_calls = []
        self.post_calls = []

    def get(self, url, params=None, timeout=None):
        self.get_calls.append((url, params or {}))

        if "filter[transaction_uuid]" in (params or {}):
            return _Response({"data": self.exact})

        page = int((params or {}).get("page", 1))
        data = self.pages[page - 1] if page <= len(self.pages) else []
        has_next = page < len(self.pages)
        return _Response({"data": data, "next_page_url": "next" if has_next else None})

    def post(self, url, json=None, timeout=None):
        self.post_calls.append((url, json or {}))
        if url.endswith("/payment"):
            return _Response({"id": 999})
        return _Response({"id": 1000})


def _transaction(tx_id, description, date="2026-09-05T19:40:29.000000Z", uuid="004272300001"):
    return {
        "id": tx_id,
        "uuid": uuid,
        "source_uuid": "2609052bGozSLzF3fwcu",
        "amount": 1,
        "description": description,
        "transaction_date": date,
    }


@pytest.fixture
def session(monkeypatch):
    stub = _SessionStub()
    monkeypatch.setattr(crm, "_session", stub)
    return stub


# --- поиск транзакции ------------------------------------------------------

def test_transaction_matches_by_description():
    tx = _transaction(1, f"44411110******61 {CHECKOUT_ID}")

    assert crm._transaction_matches(tx, CHECKOUT_ID) is True
    assert crm._transaction_matches(tx, "0000-нет-такого") is False


def test_transaction_matches_by_uuid():
    tx = _transaction(1, "Оплата за товар", uuid=CHECKOUT_ID)

    assert crm._transaction_matches(tx, CHECKOUT_ID) is True


def test_find_transaction_uses_uuid_filter_first(session):
    session.exact = [_transaction(14512, "будь-що")]

    found = crm.find_external_transaction(CHECKOUT_ID, "2026-09-05T22:40:00+03:00")

    assert found["id"] == 14512
    assert len(session.get_calls) == 1


def test_find_transaction_scans_unattached_pages(session):
    session.pages = [
        [_transaction(14514, "44411110******61 інший-checkout")],
        [_transaction(14512, f"44411110******61 {CHECKOUT_ID}")],
    ]

    found = crm.find_external_transaction(CHECKOUT_ID, "2026-09-05T22:40:00+03:00")

    assert found["id"] == 14512
    scan_params = session.get_calls[1][1]
    assert scan_params["filter[is_attached]"] == "false"


def test_find_transaction_returns_none_when_missing(session):
    session.pages = [[_transaction(14514, "44411110******61 інший-checkout")]]

    assert crm.find_external_transaction(CHECKOUT_ID, "2026-09-05T22:40:00+03:00") is None


def test_find_transaction_stops_on_transactions_older_than_order(session):
    """Не перебираем всю историю: страница целиком старше окна — выходим."""
    session.pages = [
        [_transaction(14514, "свіжа, але чужа", date="2026-09-05T19:00:00.000000Z")],
        [_transaction(14000, "стара", date="2026-01-01T10:00:00.000000Z")],
        [_transaction(13000, f"44411110******61 {CHECKOUT_ID}", date="2025-12-01T10:00:00.000000Z")],
    ]

    assert crm.find_external_transaction(CHECKOUT_ID, "2026-09-05T22:40:00+03:00") is None
    # запрошены только фильтр по uuid и две страницы перебора
    assert len(session.get_calls) == 3


# --- сквозной сценарий -----------------------------------------------------

def _order_obj(fixture):
    return SimpleNamespace(raw_json=order(fixture))


def test_attach_payment_creates_and_links_payment(session):
    session.pages = [[_transaction(14512, f"44411110******61 {CHECKOUT_ID}")]]

    result = crm.attach_payment_to_crm_order(_order_obj("PAID_DIFFERENT_PEOPLE"), 555)

    assert result["status"] == "attached"
    assert result["amount"] == 1.0
    assert result["is_partial"] is False

    payment_url, payment_body = session.post_calls[0]
    assert payment_url.endswith("/order/555/payment")
    assert payment_body["amount"] == 1.0
    assert payment_body["payment_method_id"] == crm.KEYCRM_PAYMENT_METHOD_ID == 7
    assert payment_body["status"] == "paid"

    attach_url, attach_body = session.post_calls[1]
    assert attach_url.endswith("/payments/999/external-transactions")
    assert attach_body["transaction_id"] == 14512


def test_attach_payment_uses_prepaid_amount_for_partial_orders(session):
    session.pages = [[_transaction(14512, f"9494cb38-0f81-40b1-8dbc-bf1098d98826")]]

    result = crm.attach_payment_to_crm_order(_order_obj("PARTIAL_SAME_PERSON"), 555)

    assert result["status"] == "attached"
    assert result["amount"] == 200.0
    assert result["is_partial"] is True
    assert session.post_calls[0][1]["amount"] == 200.0
    assert "Часткова оплата" in session.post_calls[0][1]["description"]


def test_no_payment_created_when_transaction_not_found(session):
    session.pages = [[_transaction(14512, "зовсім інша оплата")]]

    result = crm.attach_payment_to_crm_order(_order_obj("PAID_DIFFERENT_PEOPLE"), 555)

    assert result["status"] == "transaction_not_found"
    assert result["checkout_id"] == CHECKOUT_ID
    assert session.post_calls == []


def test_legacy_order_without_checkout_id_is_skipped(session):
    result = crm.attach_payment_to_crm_order(_order_obj("LEGACY_ORDER"), 555)

    assert result["status"] == "no_checkout_id"
    assert session.get_calls == []
    assert session.post_calls == []


def test_payment_date_is_converted_to_kyiv_time():
    assert crm._format_payment_date("2026-09-05T19:40:29.000000Z") == "2026-09-05 22:40:29"
    assert crm._format_payment_date(None) is None
