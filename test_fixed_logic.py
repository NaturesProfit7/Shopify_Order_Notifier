#!/usr/bin/env python3
"""
Тест исправленной логики адресов
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))


def test_fixed_logic():
    """Тест исправленной логики с четким разделением ролей"""

    print("🧪 ТЕСТ ИСПРАВЛЕННОЙ ЛОГИКИ АДРЕСОВ")
    print("=" * 60)

    # Ваш пример с разными адресами
    order_data = {
        "id": 6435861004591,
        "order_number": 1717,
        "shipping_address": {
            "first_name": "Valeriia",
            "last_name": "Klink",
            "phone": "0967489260",
            "address1": "142",
            "city": "Одеса"
        },
        "billing_address": {
            "first_name": "Наталія",
            "last_name": "Клінк",
            "phone": "0674219291",
            "address1": "142",
            "city": "Одеса"
        }
    }

    print(f"📋 ИСХОДНЫЕ ДАННЫЕ:")
    print(
        f"Shipping (заказчик): {order_data['shipping_address']['first_name']} {order_data['shipping_address']['last_name']}")
    print(
        f"Billing (получатель): {order_data['billing_address']['first_name']} {order_data['billing_address']['last_name']}")

    # Применяем логику
    from app.services.address_utils import (
        get_delivery_and_contact_info,
        addresses_are_same,
        build_delivery_address_text,
        get_contact_name,
        get_contact_phone_e164
    )

    shipping = order_data['shipping_address']
    billing = order_data['billing_address']

    are_same = addresses_are_same(shipping, billing)
    print(f"Адреса одинаковые: {are_same}")

    delivery_address, contact_info = get_delivery_and_contact_info(order_data)

    print(f"\n🎯 РЕЗУЛЬТАТ ЛОГИКИ:")
    print(
        f"Адрес доставки: {delivery_address['first_name']} {delivery_address['last_name']} (из {'shipping' if delivery_address == shipping else 'billing'})")
    print(
        f"Контактное лицо: {contact_info['first_name']} {contact_info['last_name']} (из {'shipping' if contact_info == shipping else 'billing'})")

    # Проверяем правильность
    assert delivery_address == billing, "❌ Адрес доставки должен быть из billing!"
    assert contact_info == shipping, "❌ Контактное лицо должно быть из shipping!"

    print("✅ Логика адресов работает правильно!")

    # Тестируем контактные данные
    contact_first, contact_last = get_contact_name(contact_info)
    contact_phone = get_contact_phone_e164(contact_info)

    print(f"\n📱 ДАННЫЕ ДЛЯ VCF:")
    print(f"Имя: {contact_first} {contact_last}")
    print(f"Телефон: {contact_phone}")

    assert contact_first == "Valeriia", "❌ VCF должен содержать имя заказчика (Valeriia)!"
    assert contact_phone == "+380967489260", "❌ VCF должен содержать телефон заказчика!"

    print("✅ VCF данные правильные!")

    # Тестируем адрес доставки
    delivery_text = build_delivery_address_text(delivery_address)
    print(f"\n📄 АДРЕС В PDF:")
    print(delivery_text)

    assert "Наталія Клінк" in delivery_text, "❌ PDF должен содержать адрес получателя (Наталія)!"

    print("✅ PDF адрес правильный!")

    # Тестируем сообщение клиенту
    from app.services.message_templates import render_simple_confirm_with_contact

    client_message = render_simple_confirm_with_contact(
        order_data,
        contact_first,
        contact_last
    )

    print(f"\n💬 СООБЩЕНИЕ КЛИЕНТУ:")
    print(client_message)

    assert "Valeriia" in client_message, "❌ Сообщение должно быть адресовано заказчику (Valeriia)!"

    print("✅ Сообщение правильно адресовано!")

    print(f"\n🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")
    return True


def test_same_addresses():
    """Тест с одинаковыми адресами"""

    print(f"\n🧪 ТЕСТ С ОДИНАКОВЫМИ АДРЕСАМИ")
    print("=" * 60)

    order_data = {
        "id": 123,
        "order_number": 123,
        "shipping_address": {
            "first_name": "Іван",
            "last_name": "Петренко",
            "phone": "+380671234567",
            "address1": "вул. Хрещатик, 1",
            "city": "Київ"
        },
        "billing_address": {
            "first_name": "Іван",
            "last_name": "Петренко",
            "phone": "+380671234567",
            "address1": "вул. Хрещатик, 1",
            "city": "Київ"
        }
    }

    from app.services.address_utils import get_delivery_and_contact_info, addresses_are_same
    from app.services.message_templates import render_simple_confirm_with_contact

    shipping = order_data['shipping_address']
    billing = order_data['billing_address']

    are_same = addresses_are_same(shipping, billing)
    print(f"Адреса одинаковые: {are_same}")

    delivery_address, contact_info = get_delivery_and_contact_info(order_data)

    # При одинаковых адресах оба должны указывать на shipping
    assert delivery_address == shipping, "❌ При одинаковых адресах доставка должна быть из shipping!"
    assert contact_info == shipping, "❌ При одинаковых адресах контакт должен быть из shipping!"

    # Сообщение должно быть адресовано тому же человеку
    from app.services.address_utils import get_contact_name
    contact_first, contact_last = get_contact_name(contact_info)

    client_message = render_simple_confirm_with_contact(
        order_data,
        contact_first,
        contact_last
    )

    print(f"Сообщение: {client_message}")
    assert "Іван" in client_message, "❌ Сообщение должно быть адресовано Івану!"

    print("✅ Одинаковые адреса обрабатываются правильно!")
    return True


def main():
    """Главная функция"""

    try:
        # Тест с разными адресами
        test_fixed_logic()

        # Тест с одинаковыми адресами
        test_same_addresses()

        print("\n" + "=" * 60)
        print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("\n📝 ИТОГОВАЯ ЛОГИКА:")
        print("🔄 Когда адреса РАЗНЫЕ:")
        print("   • Сообщение → заказчик (shipping)")
        print("   • VCF → заказчик (shipping)")
        print("   • PDF → получатель (billing)")
        print("🔄 Когда адреса ОДИНАКОВЫЕ:")
        print("   • Все → из shipping")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ ОШИБКА В ТЕСТАХ: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()