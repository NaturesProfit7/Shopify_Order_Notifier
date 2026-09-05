# tests/test_chekly_documents.py
"""PDF, текст клиенту и комментарий менеджера для заказов Chekly."""
import pytest

from app.services import pdf_service
from app.services.keycrm_service import _format_manager_comment
from app.services.message_templates import render_client_order_accepted
from tests.fixtures.chekly_orders import order


# --- вёрстка шапки PDF -----------------------------------------------------

class _CanvasStub:
    """Минимальный «холст»: ширина символа = 1, чтобы считать переносы в знаках."""

    def __init__(self):
        self.drawn = []
        self.fonts = []
        self._font_size = 10

    def setFont(self, font, size):
        self._font_size = size
        self.fonts.append(font)

    def stringWidth(self, text, font, size):
        return len(text)

    def drawString(self, x, y, text):
        self.drawn.append((x, y, text))


def test_header_wraps_into_narrow_column_next_to_logo():
    """Пока строка идёт напротив логотипа — ширина узкая, ниже — полная."""
    canvas = _CanvasStub()
    logo_bottom = 50

    def width_for(y):
        return 10 if y > logo_bottom else 40

    text = "one two three four five six seven eight"
    pdf_service._wrap_text_dynamic(canvas, text, x=0, y=60, font="F", size=1,
                                   line_step=20, width_for=width_for)

    # первая строка легла в 10 знаков, а строка ниже логотипа — целиком
    assert canvas.drawn[0][2] == "one two"
    assert canvas.drawn[-1][1] <= logo_bottom
    assert all(len(text) <= 40 for _, _, text in canvas.drawn)


def test_non_breaking_space_keeps_phone_on_one_line():
    canvas = _CanvasStub()
    phone = "+380 63 111"

    pdf_service._wrap_text_dynamic(canvas, f"Замовник: Олена {phone}", x=0, y=0,
                                   font="F", size=1, line_step=1,
                                   width_for=lambda y: 14)

    assert phone in [text for _, _, text in canvas.drawn]


def test_wrapped_lines_get_hanging_indent():
    canvas = _CanvasStub()

    pdf_service._wrap_text_dynamic(canvas, "aaa bbb ccc", x=0, y=0, font="F", size=1,
                                   line_step=1, width_for=lambda y: 4, indent=5)

    assert canvas.drawn[0][0] == 0
    assert canvas.drawn[1][0] == 5


# --- сам документ ----------------------------------------------------------

@pytest.mark.parametrize("fixture", ["PARTIAL_SAME_PERSON", "PAID_DIFFERENT_PEOPLE", "LEGACY_ORDER"])
def test_pdf_is_generated(fixture):
    pdf_bytes, filename = pdf_service.build_order_pdf(order(fixture))

    assert pdf_bytes.startswith(b"%PDF")
    assert filename.endswith(".pdf")


def test_pdf_draws_labels_in_bold_and_values_in_regular():
    canvas = _CanvasStub()

    pdf_service._draw_header_line(canvas, "Статус оплати:", "Сплачено", x=0, y=100,
                                  bold_font="BOLD", font="REG", size=1, line_step=1,
                                  width_for=lambda y: 100, indent=0)

    # заголовок и значение на одной строке, значение сдвинуто вправо
    assert [(x, text) for x, _, text in canvas.drawn] == [(0, "Статус оплати:"), (15.0, "Сплачено")]
    assert canvas.fonts == ["BOLD", "REG"]


def test_pdf_header_label_without_value_takes_a_whole_line():
    canvas = _CanvasStub()

    y = pdf_service._draw_header_line(canvas, "Замовник:", "", x=0, y=100,
                                      bold_font="BOLD", font="REG", size=1, line_step=7,
                                      width_for=lambda y: 100, indent=0)

    assert [text for _, _, text in canvas.drawn] == ["Замовник:"]
    assert y == 93


# --- текст клиенту ---------------------------------------------------------

def test_client_message_for_full_payment():
    text = render_client_order_accepted(order("PAID_DIFFERENT_PEOPLE"))

    assert text.startswith("Вітаю, Тестовий ☺️\nОтримали ваше замовлення №4582\n")
    assert "Статус оплати: повна передоплата" in text
    assert "Максимальний термін виготовлення складає 7 днів" in text
    assert "Передаємо в роботу, мирного дня 🙏" in text
    assert "Все вірно?" not in text


def test_client_message_for_partial_payment_shows_amount():
    text = render_client_order_accepted(order("PARTIAL_SAME_PERSON"))

    assert "Вітаю, Олена" in text
    assert "Статус оплати: часткова передоплата (200.00 грн)" in text


def test_client_message_hides_payment_line_for_other_statuses():
    raw = order("PAID_DIFFERENT_PEOPLE")
    raw["financial_status"] = "refunded"

    assert "Статус оплати" not in render_client_order_accepted(raw)


# --- комментарий менеджера в keyCRM ----------------------------------------

def test_manager_comment_head_matches_the_pdf_layout():
    comment = _format_manager_comment(order("PARTIAL_SAME_PERSON"))
    head = comment.splitlines()[:18]

    assert head == [
        "Замовлення №4580",
        "",
        "Дата: 05.09.2026 19:52",
        "",
        "Статус оплати: Частково сплачено",
        "Передоплата: 200.00 UAH",
        "Залишок: 350.00 UAH",
        "",
        "Замовник:",
        "Тестова Олена",
        "+380 63 111 22 33",
        "test.customer@example.com",
        "",
        "Доставка: Нова Пошта",
        "Тестова Олена",
        "+380 63 111 22 33",
        "Відділення №18 (до 30 кг): вул. Фонтанська дорога, 16/8",
        "м. Одеса, Одеська, 65049, Ukraine",
    ]


def test_manager_comment_keeps_products_and_phones_sections():
    comment = _format_manager_comment(order("PARTIAL_SAME_PERSON"))

    assert "Адресник квітка" in comment
    assert "кількість х1" in comment
    assert "• Колір медальки: золото" in comment
    assert "Сума замовлення - 550.00" in comment
    assert "Телефони:" in comment
    assert "+38•063•111•22•33" in comment


def test_manager_comment_checkout_block_is_last():
    comment = _format_manager_comment(order("PARTIAL_SAME_PERSON"), "Коментар з Telegram")
    tail = comment.splitlines()[-3:]

    assert tail == [
        "———",
        "Checkout ID: 9494cb38-0f81-40b1-8dbc-bf1098d98826",
        "Оплата: часткова — 200.00 з 550.00 UAH",
    ]
    assert "❗️❗️❗️" in comment
    assert "Коментар з Telegram" in comment


def test_manager_comment_without_checkout_id_has_no_block():
    comment = _format_manager_comment(order("LEGACY_ORDER"))

    assert "———" not in comment
    assert "Checkout ID" not in comment
