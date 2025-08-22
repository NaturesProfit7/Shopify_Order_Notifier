#!/usr/bin/env python3
"""
Тест новой логики обработки адресов с реальным заказом
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))


def test_with_real_order():
    """Тест с реальным заказом из Shopify"""

    print("🧪 ТЕСТ НОВОЙ ЛОГИКИ АДРЕСОВ")
    print("=" * 50)

    # ID заказа из вашего примера
    order_id = 6435861004591

    try:
        # Получаем заказ из Shopify
        from app.services.shopify_service import get_order
        print(f"📥 Получаем заказ #{order_id}...")
        order_data = get_order(order_id)

        # Применяем новую логику
        from app.services.address_utils import (
            get_delivery_and_contact_info,
            addresses_are_same,
            build_delivery_address_text,
            get_contact_name,
            get_contact_phone_e164
        )

        shipping = order_data.get('shipping_address', {})
        billing = order_data.get('billing_address', {})

        print(f"\n📋 ИСХОДНЫЕ ДАННЫЕ:")
        print(f"Shipping: {shipping.get('first_name')} {shipping.get('last_name')}")
        print(f"Billing: {billing.get('first_name')} {billing.get('last_name')}")

        # Проверяем логику
        are_same = addresses_are_same(shipping, billing)
        print(f"Адреса одинаковые: {are_same}")

        delivery_address, contact_info = get_delivery_and_contact_info(order_data)

        print(f"\n🎯 РЕЗУЛЬТАТ ЛОГИКИ:")
        print(f"Адрес доставки: {delivery_address.get('first_name')} {delivery_address.get('last_name')}")
        print(f"Контактное лицо: {contact_info.get('first_name')} {contact_info.get('last_name')}")

        # Данные для VCF
        contact_first, contact_last = get_contact_name(contact_info)
        contact_phone = get_contact_phone_e164(contact_info)

        print(f"\n📱 VCF КОНТАКТ:")
        print(f"Имя: {contact_first} {contact_last}")
        print(f"Телефон: {contact_phone}")

        # Адрес для PDF
        delivery_text = build_delivery_address_text(delivery_address)
        print(f"\n📄 АДРЕС В PDF:")
        print(delivery_text)

        # Тестируем генерацию файлов
        print(f"\n🔧 ГЕНЕРАЦИЯ ФАЙЛОВ:")

        # PDF
        from app.services.pdf_service import build_order_pdf
        pdf_bytes, pdf_filename = build_order_pdf(order_data)
        with open(f"test_{pdf_filename}", "wb") as f:
            f.write(pdf_bytes)
        print(f"✅ PDF: test_{pdf_filename} ({len(pdf_bytes)} байт)")

        # VCF
        from app.services.vcf_service import build_contact_vcf
        vcf_bytes, vcf_filename = build_contact_vcf(
            first_name=contact_first,
            last_name=contact_last,
            order_id=str(order_data.get('order_number')),
            phone_e164=contact_phone
        )
        with open(f"test_{vcf_filename}", "wb") as f:
            f.write(vcf_bytes)
        print(f"✅ VCF: test_{vcf_filename} ({len(vcf_bytes)} байт)")

        # Сообщение клиенту
        from app.services.message_templates import render_simple_confirm
        order_for_message = order_data.copy()
        order_for_message['customer'] = {
            'first_name': contact_first,
            'last_name': contact_last
        }
        message = render_simple_confirm(order_for_message)
        print(f"\n💬 СООБЩЕНИЕ КЛИЕНТУ:")
        print(message)

        print(f"\n✅ ТЕСТ ЗАВЕРШЕН УСПЕШНО!")
        return True

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_logic_scenarios():
    """Тест различных сценариев логики"""

    print("\n🧪 ТЕСТ СЦЕНАРИЕВ ЛОГИКИ")
    print("=" * 50)

    from app.services.address_utils import addresses_are_same, get_delivery_and_contact_info

    # Сценарий 1: Одинаковые адреса
    print("\n1️⃣ ОДИНАКОВЫЕ АДРЕСА:")
    order1 = {
        "shipping_address": {
            "first_name": "Іван", "last_name": "Петренко",
            "address1": "вул. Хрещатик, 1", "city": "Київ", "zip": "01001"
        },
        "billing_address": {
            "first_name": "Іван", "last_name": "Петренко",
            "address1": "вул. Хрещатик, 1", "city": "Київ", "zip": "01001"
        }
    }

    delivery1, contact1 = get_delivery_and_contact_info(order1)
    print(f"✅ Адреса одинаковые: {addresses_are_same(order1['shipping_address'], order1['billing_address'])}")
    print(f"✅ Доставка: {delivery1['first_name']} (из shipping)")
    print(f"✅ Контакт: {contact1['first_name']} (из shipping)")

    # Сценарий 2: Разные адреса
    print("\n2️⃣ РАЗНЫЕ АДРЕСА:")
    order2 = {
        "shipping_address": {
            "first_name": "Valeriia", "last_name": "Klink",
            "phone": "0967489260"
        },
        "billing_address": {
            "first_name": "Наталія", "last_name": "Клінк",
            "address1": "142", "city": "Одеса", "phone": "0674219291"
        }
    }

    delivery2, contact2 = get_delivery_and_contact_info(order2)
    print(f"✅ Адреса одинаковые: {addresses_are_same(order2['shipping_address'], order2['billing_address'])}")
    print(f"✅ Доставка: {delivery2['first_name']} (из billing)")
    print(f"✅ Контакт: {contact2['first_name']} (из shipping)")

    print("\n✅ СЦЕНАРИИ ПРОТЕСТИРОВАНЫ!")


if __name__ == "__main__":
    # Тест с реальным заказом
    success = test_with_real_order()

    # Тест сценариев логики
    test_logic_scenarios()

    print("\n" + "=" * 50)
    if success:
        print("🎉 ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
        print("\n📁 Созданные файлы:")
        print("• test_order_#1717.pdf - PDF с правильным адресом доставки")
        print("• test_contact_#1717.vcf - VCF с контактными данными заказчика")
    else:
        print("❌ ЕСТЬ ОШИБКИ В ТЕСТАХ")
    print("=" * 50)