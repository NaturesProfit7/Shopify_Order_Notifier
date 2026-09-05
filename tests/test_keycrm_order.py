# tests/test_keycrm_order.py
"""Создание замовлення в keyCRM: покупець і отримувач."""
import json as json_module
from types import SimpleNamespace

import pytest
import requests

from app.services import keycrm_service as crm
from app.services.order_fields import get_order_contact
from tests.fixtures.chekly_orders import order


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.reason = "OK" if self.ok else "Error"
        self.text = json_module.dumps(payload)

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self._payload


class _SessionStub:
    """Подменяет requests.Session и запоминает, что ушло в keyCRM.

    `failures` — коды ответа для первых попыток, дальше отвечает успехом.
    """

    def __init__(self, failures=()):
        self.post_calls = []
        self.failures = list(failures)

    def post(self, url, json=None, timeout=None, allow_redirects=True):
        self.post_calls.append((url, json or {}))
        if self.failures:
            status = self.failures.pop(0)
            return _Response({"message": "нема"}, status_code=status)
        return _Response({"id": 1000})


@pytest.fixture
def session(monkeypatch):
    stub = _SessionStub()
    monkeypatch.setattr(crm, "_session", stub)
    return stub


def _create(fixture, order_number="4582"):
    raw = order(fixture)
    first_name, last_name, phone = get_order_contact(raw)
    return crm.create_crm_order(SimpleNamespace(
        id=1, order_number=order_number, comment=None, raw_json=raw,
        customer_first_name=first_name, customer_last_name=last_name,
        customer_phone_e164=phone,
    ))


def test_crm_order_sends_customer_as_buyer(session):
    _create("PAID_DIFFERENT_PEOPLE")

    _, body = session.post_calls[0]
    assert body["buyer"] == {
        "full_name": "Тестовий Замовник",
        "phone": "+380931112255",
        "email": "buyer@example.com",
    }


def test_recipient_goes_separately_when_it_is_another_person(session):
    _create("PAID_DIFFERENT_PEOPLE")

    shipping = session.post_calls[0][1]["shipping"]
    assert shipping["recipient_full_name"] == "Тестовий Отримувач"
    assert shipping["recipient_phone"] == "+380931112244"


# --- адреса доставки --------------------------------------------------------

def test_shipping_binds_the_nova_poshta_warehouse(session):
    _create("PARTIAL_SAME_PERSON", "4580")

    shipping = session.post_calls[0][1]["shipping"]
    assert shipping["delivery_service_id"] == crm.KEYCRM_DELIVERY_SERVICE_ID == 2
    assert shipping["warehouse_ref"] == "1ec09d48-e1c2-11e3-8c4a-0050568002cf"
    assert shipping["shipping_address_city"] == "м. Одеса"
    assert shipping["shipping_address_region"] == "Одеська"
    assert shipping["shipping_address_zip"] == "65049"
    assert shipping["shipping_receive_point"].startswith("Відділення №18")


def test_address_goes_even_when_customer_is_the_recipient(session):
    """Раньше блок shipping уходил только при разных людях — теперь всегда."""
    _create("PARTIAL_SAME_PERSON", "4580")

    shipping = session.post_calls[0][1]["shipping"]
    assert "recipient_full_name" not in shipping
    assert shipping["shipping_address_city"] == "м. Одеса"


def test_falls_back_to_plain_address_when_warehouse_is_rejected(session):
    """keyCRM отверг привязку склада — замовлення всё равно создаётся."""
    session.failures = [422]

    result = _create("PARTIAL_SAME_PERSON", "4580")

    assert result["id"] == 1000
    assert len(session.post_calls) == 2
    assert "warehouse_ref" in session.post_calls[0][1]["shipping"]
    assert "warehouse_ref" not in session.post_calls[1][1]["shipping"]
    assert session.post_calls[1][1]["shipping"]["shipping_address_city"] == "м. Одеса"


def test_falls_back_to_no_shipping_at_all(session):
    session.failures = [422, 422]

    result = _create("PARTIAL_SAME_PERSON", "4580")

    assert result["id"] == 1000
    assert len(session.post_calls) == 3
    assert "shipping" not in session.post_calls[2][1]


def test_server_errors_are_not_retried(session):
    """При 5xx замовлення могло створитись — повтор зробив би дубль."""
    session.failures = [500, 500, 500]

    with pytest.raises(requests.HTTPError):
        _create("PARTIAL_SAME_PERSON", "4580")

    assert len(session.post_calls) == 1


def test_legacy_orders_send_plain_address(session):
    """У старых заказов нет ref склада, но служба доставки та же."""
    _create("LEGACY_ORDER", "3475")

    shipping = session.post_calls[0][1]["shipping"]
    assert "warehouse_ref" not in shipping
    assert shipping["delivery_service_id"] == 2
    assert shipping["shipping_address_city"] == "Одеса"
    assert shipping["shipping_receive_point"] == "Відділення №5"


# --- поштомат і кур'єр ------------------------------------------------------

def test_postomat_binds_the_warehouse_like_a_branch(session):
    """У почтомата тот же _delivery_type «branch» и свой warehouse_ref."""
    _create("POSTOMAT_ORDER", "4586")

    shipping = session.post_calls[0][1]["shipping"]
    assert shipping["warehouse_ref"] == "96840b3f-7f22-11ef-98f8-d4f5ef0df2b9"
    assert shipping["delivery_service_id"] == 2
    assert shipping["shipping_receive_point"].startswith('Поштомат "Нова Пошта" №44666')
    # адреса складу дублювала б точку видачі — keyCRM добудує її сама з ref
    assert "shipping_secondary_line" not in shipping


def test_city_with_a_district_keeps_city_and_region(session):
    """«с. Абазівка, Полтавський, Полтавська» — район между городом и областью."""
    _create("POSTOMAT_ORDER", "4586")

    shipping = session.post_calls[0][1]["shipping"]
    assert shipping["shipping_address_city"] == "с. Абазівка"
    assert shipping["shipping_address_region"] == "Полтавська"


def test_courier_goes_without_a_warehouse(session):
    """У курьера склада нет — улица уходит дополнительной адресой."""
    _create("COURIER_ORDER", "4587")

    shipping = session.post_calls[0][1]["shipping"]
    assert "warehouse_ref" not in shipping
    assert "shipping_receive_point" not in shipping
    assert shipping["shipping_secondary_line"] == "вул.1-а Вишнева, буд.12, кв.55"
    # до служби доставки замовлення все одно прив'язуємо
    assert shipping["delivery_service_id"] == 2


# --- звіт про перенесення адреси -------------------------------------------

def test_result_reports_a_bound_warehouse(session):
    result = _create("POSTOMAT_ORDER", "4586")

    assert result["shipping_kind"] == "warehouse"
    assert result["shipping_degraded"] is False


def test_result_reports_a_courier_address(session):
    result = _create("COURIER_ORDER", "4587")

    assert result["shipping_kind"] == "courier"
    assert result["shipping_degraded"] is False


def test_result_reports_a_fallback_to_plain_address(session):
    session.failures = [422]

    result = _create("POSTOMAT_ORDER", "4586")

    assert result["shipping_kind"] == "address"
    assert result["shipping_degraded"] is True


def test_result_reports_that_delivery_was_dropped(session):
    session.failures = [422, 422]

    result = _create("POSTOMAT_ORDER", "4586")

    assert result["shipping_kind"] == "none"
    assert result["shipping_degraded"] is True
