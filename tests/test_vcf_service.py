# tests/test_vcf_service.py
from app.services.vcf_service import build_contact_vcf

def _decode(v: bytes) -> str:
    return v.decode("utf-8")

def test_vcf_with_phone_and_embed_in_n():
    data, fname = build_contact_vcf(
        first_name="Іван",
        last_name="Петренко",
        order_id="1694",
        phone_e164="+380672326239",
        embed_order_in_n=True,
    )
    text = _decode(data)
    assert fname == "contact_#1694.vcf"
    assert "BEGIN:VCARD\r\n" in text
    assert "\r\nEND:VCARD\r\n" in text
    # FN и N должны содержать #заказ
    assert "FN:Іван Петренко — #1694" in text
    assert "N:Петренко — #1694;Іван;;;" in text
    assert "TEL;TYPE=CELL:+380672326239" in text

def test_vcf_without_phone():
    data, _ = build_contact_vcf(
        first_name="Марія",
        last_name="Коваль",
        order_id="42",
        phone_e164=None,
        embed_order_in_n=True,
    )
    text = _decode(data)
    assert "TEL" not in text  # поля нет
    assert "FN:Марія Коваль — #42" in text
    assert "N:Коваль — #42;Марія;;;" in text

def test_vcf_only_order_id():
    data, _ = build_contact_vcf(
        first_name="",
        last_name="",
        order_id="7",
        phone_e164=None,
        embed_order_in_n=True,
    )
    text = _decode(data)
    # Если имени нет — FN станет "#7"
    assert "FN:#7" in text
    # В N помещаем #7 в фамилию, чтобы iOS показал номер
    assert "N:#7;;;;" in text
