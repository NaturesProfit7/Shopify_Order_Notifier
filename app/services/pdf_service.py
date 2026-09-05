# app/services/pdf_service.py - ОБНОВЛЕННАЯ ВЕРСИЯ
from __future__ import annotations
from io import BytesIO
from datetime import datetime
from typing import Tuple, List, Dict, Any
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

from app.services.order_fields import build_header_blocks

FNT_REGULAR = "DejaVuSans"
FNT_BOLD = "DejaVuSans-Bold"

# Отступ между текстовой колонкой шапки и логотипом
BRAND_GAP_MM = 5.0

# Пустая строка между смысловыми блоками шапки
HEADER_BLOCK_GAP_MM = 3.4


# ---------- fonts ----------
def _register_fonts() -> bool:
    """Регистрируем DejaVu Sans; если файлов нет — остаёмся на Helvetica."""
    try:
        base = Path(__file__).resolve().parents[1] / "assets" / "fonts"
        pdfmetrics.registerFont(TTFont(FNT_REGULAR, str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont(FNT_BOLD, str(base / "DejaVuSans-Bold.ttf")))
        return True
    except Exception:
        return False


# ---------- small helpers ----------
def _fmt_date(dt_str: str | None) -> str:
    """created_at → 'dd.mm.yyyy HH:MM' (без смены TZ)."""
    if not dt_str:
        return datetime.now().strftime("%d.%m.%Y %H:%M")
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return datetime.now().strftime("%d.%m.%Y %H:%М")


def _currency(order: dict) -> str:
    return (order.get("currency") or order.get("presentment_currency") or "UAH").upper()


def _money(value: float, cur: str) -> str:
    return f"{value:,.2f}".replace(",", " ") + f" {cur}"


def _wrap_text(c: canvas.Canvas, text: str, x: float, y: float, max_width: float,
               font: str, size: int, line_step: float) -> float:
    """Рисуем текст с переносами по ширине. Возвращаем новую y после отрисовки."""
    c.setFont(font, size)
    words = str(text).split()
    line = ""
    for w in words:
        trial = (line + " " + w).strip()
        if c.stringWidth(trial, font, size) <= max_width:
            line = trial
        else:
            if line:
                c.drawString(x, y, line)
                y -= line_step
            line = w
    if line:
        c.drawString(x, y, line)
        y -= line_step
    return y


def _draw_header_line(c: canvas.Canvas, label: str, value: str, x: float, y: float, *,
                      bold_font: str, font: str, size: int, line_step: float,
                      width_for, indent: float) -> float:
    """Строка шапки: заголовок жирным, значение обычным шрифтом следом.

    Заголовок без значения («Замовник:») занимает строку целиком, значение
    без заголовка — обычная строка данных.
    """
    offset = 0.0
    if label:
        c.setFont(bold_font, size)
        c.drawString(x, y, label)
        if not value:
            return y - line_step
        offset = c.stringWidth(f"{label} ", bold_font, size)

    return _wrap_text_dynamic(c, value, x, y, font, size, line_step, width_for,
                              indent=indent, first_offset=offset)


def _wrap_text_dynamic(c: canvas.Canvas, text: str, x: float, y: float,
                       font: str, size: int, line_step: float,
                       width_for, indent: float = 0.0,
                       first_offset: float = 0.0) -> float:
    """Как `_wrap_text`, но доступная ширина зависит от текущей строки.

    Нужно для шапки: пока строка идёт напротив логотипа, текст верстается
    в узкую левую колонку, ниже логотипа — на всю ширину страницы.
    `width_for(y)` возвращает доступную ширину для строки с базовой линией `y`,
    `indent` — втяжка строк переноса, `first_offset` — отступ первой строки
    (например, под уже нарисованный жирный заголовок).

    Разбиваем только по обычным пробелам: неразрывный пробел (U+00A0) держит
    вместе, например, телефон.
    """
    c.setFont(font, size)
    words = [w for w in str(text).replace("\t", " ").split(" ") if w]
    if not words:
        return y

    line = ""
    offset = first_offset
    index = 0
    while index < len(words):
        word = words[index]
        trial = f"{line} {word}".strip()
        if not line or c.stringWidth(trial, font, size) <= width_for(y) - offset:
            line = trial
            index += 1
        else:
            c.drawString(x + offset, y, line)
            y -= line_step
            line = ""
            offset = indent

    if line:
        c.drawString(x + offset, y, line)
        y -= line_step
    return y


def _draw_properties(c: canvas.Canvas, props: List[Dict[str, Any]], x: float, y: float,
                     usable_w: float, font: str, size: int, step: float, bullet="• ") -> float:
    """Список свойств товара (пропуская имена, начинающиеся с '_')."""
    for p in props or []:
        name = str(p.get("name") or "").strip()
        value = str(p.get("value") or "").strip()
        if not name or name.startswith("_"):
            continue
        text = f"{bullet}{name}: {value}" if value else f"{bullet}{name}"
        y = _wrap_text(c, text, x, y, usable_w, font, size, step)
    return y


def _try_draw_brand(c: canvas.Canvas, x_right: float, y_top: float, *,
                    max_w_mm: float, max_h_mm: float) -> Tuple[float, float] | None:
    """
    Рисует картинку (если найдена) в правом верхнем углу.
    Ищем: app/assets/img/brand.(png|jpg|webp)

    Возвращает (x_left, y_bottom) реально отрисованного логотипа — по этим
    координатам шапка документа обходит картинку, чтобы текст на неё не налазил.
    """
    try:
        base = Path(__file__).resolve().parents[1] / "assets" / "img"
        for name in ("brand.png", "brand.jpg", "brand.webp"):
            p = base / name
            if p.exists():
                img = ImageReader(str(p))
                iw, ih = img.getSize()
                max_w = max_w_mm * mm
                max_h = max_h_mm * mm
                scale = min(max_w / iw, max_h / ih)
                w, h = iw * scale, ih * scale
                c.drawImage(img, x_right - w, y_top - h, width=w, height=h,
                            preserveAspectRatio=True, mask="auto")
                return x_right - w, y_top - h
    except Exception:
        pass
    return None


# ---------- main ----------
def build_order_pdf(order: dict) -> Tuple[bytes, str]:
    """
    Накладная заказа.

    Шапка (данные берутся из note_attributes Chekly, см. order_fields) —
    заголовки жирным, между блоками пустая строка:

        Дата: 05.09.2026 19:52

        Статус оплати: Частково сплачено
        Передоплата: 200.00 UAH          — только при частичной оплате
        Залишок: 350.00 UAH

        Замовник:
        Ковальова Анна
        +380 63 317 44 76
        anakovalova075@gmail.com

        Доставка: Нова Пошта
        Адреса доставки:
        Ковальова Анна
        +380 63 317 44 76
        Відділення №18 (до 30 кг): вул. Фонтанська дорога, 16/8
        м. Одеса, Одеська, 65049, Ukraine

    Пока строки идут напротив логотипа, они верстаются в узкую левую колонку.
    """
    import time
    import logging
    logger = logging.getLogger(__name__)
    
    start_time = time.time()
    order_id = order.get('id', 'unknown')
    buf = BytesIO()
    # Создаем PDF с минимальными настройками для уменьшения размера
    c = canvas.Canvas(buf, pagesize=A4, compress=1)  # Включаем сжатие
    width, height = A4
    has_fonts = _register_fonts()

    order_no = order.get("order_number") or order.get("id") or "—"
    created = _fmt_date(order.get("created_at"))
    cur = _currency(order)

    # Разметка страницы
    top = height - 20 * mm
    x0 = 20 * mm
    right = width - x0

    title_font = FNT_BOLD if has_fonts else "Helvetica-Bold"
    text_font = FNT_REGULAR if has_fonts else "Helvetica"

    # Заголовок
    c.setTitle(f"Замовлення #{order_no}")
    c.setFont(title_font, 16)
    c.drawString(x0, top, f"Замовлення №{order_no}")

    # Бренд справа сверху — сдвинут ближе к краю листа, чтобы освободить
    # место под текстовую колонку шапки
    brand_box = _try_draw_brand(c, x_right=width - 8 * mm, y_top=top + 2 * mm,
                                max_w_mm=89.25, max_h_mm=51.0)

    header_size = 10
    header_step = 5.4 * mm

    def header_width(y_line: float) -> float:
        """Ширина строки шапки: узкая колонка напротив логотипа, ниже — полная."""
        if brand_box is None:
            return right - x0
        brand_x_left, brand_y_bottom = brand_box
        # строка занимает по высоте примерно от y_line до y_line + размер шрифта
        if y_line + header_size < brand_y_bottom:
            return right - x0
        return max(brand_x_left - BRAND_GAP_MM * mm - x0, 30 * mm)

    # Шапка: заголовки жирным, между смысловыми блоками — пустая строка
    y = top - 10 * mm
    for index, block in enumerate(build_header_blocks(order, created)):
        if index:
            y -= HEADER_BLOCK_GAP_MM * mm
        for label, value in block:
            y = _draw_header_line(c, label, value, x0, y,
                                  bold_font=title_font, font=text_font,
                                  size=header_size, line_step=header_step,
                                  width_for=header_width, indent=6 * mm)

    # Товары начинаем ниже логотипа, даже если шапка получилась короткой
    if brand_box is not None:
        y = min(y, brand_box[1] - 6 * mm)

    y -= 7 * mm

    # Заголовок таблицы товаров
    c.setFont(title_font, 12)
    c.drawString(x0, y, "Товари")
    y -= 7 * mm

    c.setFont(title_font, 10)
    # колонки
    col_name_x = x0
    col_qty_x = x0 + 112 * mm
    col_price_x = x0 + 140 * mm
    col_sum_x = x0 + 180 * mm

    c.drawString(col_name_x, y, "Назва")
    c.drawRightString(col_qty_x, y, "К-ть")
    c.drawRightString(col_price_x, y, "Ціна")
    c.drawRightString(col_sum_x, y, "Сума")

    y -= 4 * mm
    c.line(x0, y, right, y)
    y -= 6 * mm
    c.setFont(text_font, 10)

    # Рендер строк
    line_items = order.get("line_items") or []
    subtotal = 0.0

    def ensure_space(min_y: float = 25 * mm):
        nonlocal y
        if y < min_y:
            c.showPage()
            c.setFont(text_font, 10)
            y = height - 20 * mm

    for it in line_items:
        title = str(it.get("title") or "—")
        qty = int(it.get("quantity") or 0)
        price = float(it.get("price") or 0.0)
        total = qty * price
        subtotal += total

        usable_w = (col_qty_x - 3 * mm) - col_name_x
        y = _wrap_text(c, title, col_name_x, y, usable_w, text_font, 10, 5.5 * mm)

        c.drawRightString(col_qty_x, y + 5.5 * mm, str(qty))
        c.drawRightString(col_price_x, y + 5.5 * mm, f"{price:,.2f}".replace(",", " "))
        c.drawRightString(col_sum_x, y + 5.5 * mm, f"{total:,.2f}".replace(",", " "))

        ensure_space()

        # Выводим размер из variant_title если есть
        variant_title = str(it.get("variant_title") or "").strip()
        if variant_title:
            y -= 1.5 * mm
            text = f"• Розмір: {variant_title}"
            y = _wrap_text(c, text, col_name_x + 6 * mm, y, right - (col_name_x + 6 * mm), text_font, 9, 5 * mm)
            ensure_space()

        props = it.get("properties") or []
        if props:
            y -= 1.5 * mm
            y = _draw_properties(c, props, col_name_x + 6 * mm, y,
                                 right - (col_name_x + 6 * mm), text_font, 9, 5 * mm)
            ensure_space()

        y -= 3 * mm

    # Разом
    total_price = None
    for key in ("total_price", "current_total_price"):
        if order.get(key):
            try:
                total_price = float(order.get(key))
                break
            except Exception:
                pass
    grand_total_str = _money(total_price if total_price is not None else subtotal, cur)

    c.setFont(title_font, 11)
    c.drawRightString(col_sum_x, y, f"Разом: {grand_total_str}")

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    
    generation_time = time.time() - start_time
    logger.info(f"PDF generation completed in {generation_time:.2f}s for order {order_id}")

    return pdf_bytes, f"order_#{order_no}.pdf"