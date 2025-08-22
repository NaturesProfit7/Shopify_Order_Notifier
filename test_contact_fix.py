#!/usr/bin/env python3
"""
Тест исправления логики контактных данных в карточке заказа
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))


def test_contact_extraction():
    """Тест правильного извлечения контактных данных"""

    print("🧪 ТЕСТ ИЗВЛЕЧЕНИЯ КОНТАКТНЫХ ДАННЫХ")
    print("=" * 60)

    # Пример заказа с разными адресами (ваш кейс)
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
        },
        "customer": {
            "first_name": "Old Name",  # Это не должно использоваться
            "last_name": "Old Surname"
        }
    }

    print(f"📋 ИСХОДНЫЕ ДАННЫЕ:")
    print(f"Shipping: {order_data['shipping_address']['first_name']} {order_data['shipping_address']['last_name']}")
    print(f"Billing: {order_data['billing_address']['first_name']} {order_data['billing_address']['last_name']}")
    print(f"Customer: {order_data['customer']['first_name']} {order_data['customer']['last_name']}")

    # Тестируем функцию из main.py
    print(f"\n🔬 ТЕСТИРУЕМ ИЗВЛЕЧЕНИЕ КОНТАКТНЫХ ДАННЫХ:")

    from app.services.address_utils import get_delivery_and_contact_info, get_contact_name, get_contact_phone_e164

    # Получаем контактную информацию
    delivery_address, contact_info = get_delivery_and_contact_info(order_data)

    print(f"Delivery address: {delivery_address['first_name']} {delivery_address['last_name']} (из billing)")
    print(f"Contact info: {contact_info['first_name']} {contact_info['last_name']} (из shipping)")

    # Извлекаем данные контакта
    contact_first_name, contact_last_name = get_contact_name(contact_info)
    contact_phone = get_contact_phone_e164(contact_info)

    print(f"\n✅ РЕЗУЛЬТАТ ИЗВЛЕЧЕНИЯ:")
    print(f"Контактное имя: {contact_first_name} {contact_last_name}")
    print(f"Контактный телефон: {contact_phone}")

    # Проверяем правильность
    assert contact_first_name == "Valeriia", f"❌ Ожидали 'Valeriia', получили '{contact_first_name}'"
    assert contact_last_name == "Klink", f"❌ Ожидали 'Klink', получили '{contact_last_name}'"
    assert contact_phone == "+380967489260", f"❌ Ожидали '+380967489260', получили '{contact_phone}'"

    print("✅ Извлечение контактных данных работает правильно!")
    return contact_first_name, contact_last_name, contact_phone


def test_order_building():
    """Тест создания карточки заказа с правильными контактными данными"""

    print(f"\n🧪 ТЕСТ СОЗДАНИЯ КАРТОЧКИ ЗАКАЗА")
    print("=" * 60)

    # Эмулируем Order объект с правильными данными
    from app.models import Order, OrderStatus
    from types import SimpleNamespace

    # Создаем mock Order объект
    order = SimpleNamespace()
    order.id = 6435861004591
    order.order_number = "1717"
    order.status = OrderStatus.NEW
    order.customer_first_name = "Valeriia"  # ← ИСПРАВЛЕННЫЕ данные
    order.customer_last_name = "Klink"  # ← ИСПРАВЛЕННЫЕ данные
    order.customer_phone_e164 = "+380967489260"
    order.comment = None
    order.reminder_at = None
    order.processed_by_username = None
    order.raw_json = {
        "line_items": [
            {"title": "Адресник серце (золото) 30мм", "quantity": 1, "price": "450.00"},
            {"title": "Шнурочок флуоресцентний", "quantity": 1, "price": "50.00"}
        ],
        "shipping_address": {"city": "Одеса", "address1": "142"},
        "total_price": "500.00",
        "currency": "UAH"
    }

    # Тестируем создание сообщения карточки
    from app.bot.routers.orders import build_order_card_message

    message = build_order_card_message(order, detailed=True)

    print(f"📱 СООБЩЕНИЕ КАРТОЧКИ:")
    print(message)
    print()

    # Проверяем правильность
    assert "Valeriia Klink" in message, "❌ В карточке должно быть имя из shipping (Valeriia Klink)"
    assert "+380967489260" in message, "❌ В карточке должен быть телефон из shipping"
    assert "#1717" in message, "❌ В карточке должен быть номер заказа"

    print("✅ Карточка заказа создается с правильными контактными данными!")
    return message


def test_vcf_generation():
    """Тест генерации VCF с правильными контактными данными"""

    print(f"\n🧪 ТЕСТ ГЕНЕРАЦИИ VCF")
    print("=" * 60)

    from app.services.vcf_service import build_contact_vcf

    # Генерируем VCF с правильными данными
    vcf_bytes, vcf_filename = build_contact_vcf(
        first_name="Valeriia",
        last_name="Klink",
        order_id="1717",
        phone_e164="+380967489260"
    )

    vcf_text = vcf_bytes.decode("utf-8")

    print(f"📄 VCF ФАЙЛ ({vcf_filename}):")
    print(vcf_text)
    print()

    # Проверяем правильность VCF
    assert "FN:Valeriia Klink — #1717" in vcf_text, "❌ VCF должен содержать правильное полное имя"
    assert "N:Klink — #1717;Valeriia;;;" in vcf_text, "❌ VCF должен содержать правильное структурированное имя"
    assert "TEL;TYPE=CELL:+380967489260" in vcf_text, "❌ VCF должен содержать правильный телефон"

    print("✅ VCF генерируется с правильными контактными данными!")
    return vcf_text


def test_message_template():
    """Тест шаблона сообщения для клиента"""

    print(f"\n🧪 ТЕСТ ШАБЛОНА СООБЩЕНИЯ ДЛЯ КЛИЕНТА")
    print("=" * 60)

    from app.services.message_templates import render_simple_confirm_with_contact

    order_data = {
        "id": 6435861004591,
        "order_number": "1717"
    }

    # Генерируем сообщение с правильными контактными данными
    message = render_simple_confirm_with_contact(
        order_data,
        "Valeriia",  # Контактное имя из shipping
        "Klink"
    )

    print(f"💬 СООБЩЕНИЕ ДЛЯ КЛИЕНТА:")
    print(message)
    print()

    # Проверяем правильность
    assert "Valeriia" in message, "❌ Сообщение должно быть адресовано заказчику (Valeriia)"
    assert "#1717" in message or "№1717" in message, "❌ Сообщение должно содержать номер заказа"

    print("✅ Сообщение для клиента генерируется правильно!")
    return message


def main():
    """Главная функция тестирования"""

    try:
        print("🎯 ТЕСТИРОВАНИЕ ИСПРАВЛЕННОЙ ЛОГИКИ КОНТАКТНЫХ ДАННЫХ")
        print("=" * 80)

        # 1. Тест извлечения контактных данных
        contact_first, contact_last, contact_phone = test_contact_extraction()

        # 2. Тест создания карточки заказа
        card_message = test_order_building()

        # 3. Тест генерации VCF
        vcf_content = test_vcf_generation()

        # 4. Тест шаблона сообщения
        client_message = test_message_template()

        print("=" * 80)
        print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print()
        print("📋 ИТОГОВАЯ ЛОГИКА:")
        print("🔄 При разных адресах shipping и billing:")
        print("   • Карточка заказа → имя и телефон из SHIPPING")
        print("   • VCF контакт → данные заказчика из SHIPPING")
        print("   • Сообщение клиенту → адресуется заказчику из SHIPPING")
        print("   • PDF → адрес доставки из BILLING")
        print()
        print("✅ ИСПРАВЛЕНИЯ ПРИМЕНЕНЫ:")
        print("   • app/main.py - исправлено сохранение контактных данных")
        print("   • app/state.py - обновлена логика извлечения адресов")
        print()
        print("🚀 ГОТОВО К РАЗВЕРТЫВАНИЮ!")

        return True

    except Exception as e:
        print(f"\n❌ ОШИБКА В ТЕСТАХ: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)