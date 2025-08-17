# app/services/pdf_service.py
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

from app.services.phone_utils import normalize_ua_phone

FNT_REGULAR = "DejaVuSans"
FNT_BOLD = "DejaVuSans-Bold"

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

def _shipping_title(order: dict) -> str:
    lines = order.get("shipping_lines") or []
    if lines:
        title = (lines[0].get("title") or "").strip()
        if title:
            return title
    return "—"

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

def _format_phone_spaced(e164: str | None) -> str:
    """
    '+380636316824' -> '+380 63 631 68 24'
    Если не E.164, вернём '—'.
    """
    if not e164 or not (e164.startswith("+380") and len(e164) == 13 and e164[1:].isdigit()):
        return "—"
    return f"{e164[:4]} {e164[4:6]} {e164[6:9]} {e164[9:11]} {e164[11:]}"

def _format_shipping_block(order: dict) -> List[str]:
    """
    Возвращает строки для блока 'Дані для відправки':
      Full Name, address1, address2, city, zip, country, телефон (с пробелами)
    """
    ship = (order.get("shipping_address") or {})
    full_name = f"{(ship.get('first_name') or '').strip()} {(ship.get('last_name') or '').strip()}".strip()
    phone_e164 = normalize_ua_phone(
        ship.get("phone")
        or (order.get("customer") or {}).get("phone")
        or (order.get("billing_address") or {}).get("phone")
        or order.get("phone")
    )
    phone_str = _format_phone_spaced(phone_e164)

    lines: List[str] = []
    if full_name:
        lines.append(full_name)
    for part in [
        (ship.get("address1") or "").strip(),
        (ship.get("address2") or "").strip(),
        (ship.get("city") or "").strip(),
        (ship.get("zip") or "").strip(),
        (ship.get("country") or "").strip(),
    ]:
        if part:
            lines.append(part)
    if phone_str and phone_str != "—":
        lines.append(phone_str)
    return lines or ["—"]

def _try_draw_brand(c: canvas.Canvas, x_right: float, y_top: float, *, max_w_mm: float, max_h_mm: float):
    """
    Рисует картинку (если найдена) в правом верхнем углу.
    Ищем: app/assets/img/brand.(png|jpg|webp)
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
                return
    except Exception:
        pass

# ---------- main ----------
def build_order_pdf(order: dict) -> Tuple[bytes, str]:
    """
    Макет:
      Замовлення №{order_number}
      Дата / Доставка / Дані для відправки (многострочно)
      Таблица товаров + properties (без '_' ключей)
      Разом
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    has_fonts = _register_fonts()

    order_no   = order.get("order_number") or order.get("id") or "—"
    created    = _fmt_date(order.get("created_at"))
    ship_title = _shipping_title(order)
    ship_block = _format_shipping_block(order)
    cur = _currency(order)

    # Разметка страницы
    top = height - 20*mm
    x0  = 20*mm
    right = width - x0

    title_font = FNT_BOLD if has_fonts else "Helvetica-Bold"
    text_font  = FNT_REGULAR if has_fonts else "Helvetica"

    # Заголовок
    c.setTitle(f"Замовлення #{order_no}")
    c.setFont(title_font, 16)
    c.drawString(x0, top, f"Замовлення №{order_no}")

    # Бренд справа сверху — уменьшено на 15% от предыдущего (105×60 мм → 89.25×51 мм)
    _try_draw_brand(c, x_right=right, y_top=top + 2*mm, max_w_mm=89.25, max_h_mm=51.0)

    # Шапка
    y = top - 10*mm
    c.setFont(text_font, 11)
    c.drawString(x0, y, f"Дата: {created}")
    y -= 6.2*mm
    c.drawString(x0, y, f"Доставка: {ship_title}")
    y -= 6.2*mm

    # Дані для відправки — вернули прежний интервал и убрали левый отступ у строк
    c.setFont(text_font, 11)
    c.drawString(x0, y, "Дані для відправки:")
    y -= 5.2*mm  # прежний зазор
    for line in ship_block:
        y = _wrap_text(c, line, x0, y, right - x0, text_font, 11, 5.2*mm)
    y -= 7*mm

    # Заголовок таблицы товаров
    c.setFont(title_font, 12)
    c.drawString(x0, y, "Товари")
    y -= 7*mm

    c.setFont(title_font, 10)
    # колонки
    col_name_x  = x0
    col_qty_x   = x0 + 112*mm
    col_price_x = x0 + 140*mm
    col_sum_x   = x0 + 180*mm

    c.drawString(col_name_x,  y, "Назва")
    c.drawRightString(col_qty_x,   y, "К-ть")
    c.drawRightString(col_price_x, y, "Ціна")
    c.drawRightString(col_sum_x,   y, "Сума")

    y -= 4*mm
    c.line(x0, y, right, y)
    y -= 6*mm
    c.setFont(text_font, 10)

    # Рендер строк
    line_items = order.get("line_items") or []
    subtotal = 0.0

    def ensure_space(min_y: float = 25*mm):
        nonlocal y
        if y < min_y:
            c.showPage()
            c.setFont(text_font, 10)
            y = height - 20*mm

    for it in line_items:
        title = str(it.get("title") or "—")
        qty   = int(it.get("quantity") or 0)
        price = float(it.get("price") or 0.0)
        total = qty * price
        subtotal += total

        usable_w = (col_qty_x - 3*mm) - col_name_x
        y = _wrap_text(c, title, col_name_x, y, usable_w, text_font, 10, 5.5*mm)

        c.drawRightString(col_qty_x,   y + 5.5*mm, str(qty))
        c.drawRightString(col_price_x, y + 5.5*mm, f"{price:,.2f}".replace(",", " "))
        c.drawRightString(col_sum_x,   y + 5.5*mm, f"{total:,.2f}".replace(",", " "))

        ensure_space()

        props = it.get("properties") or []
        if props:
            y -= 1.5*mm
            y = _draw_properties(c, props, col_name_x + 6*mm, y,
                                 right - (col_name_x + 6*mm), text_font, 9, 5*mm)
            ensure_space()

        y -= 3*mm

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

    return pdf_bytes, f"order_#{order_no}.pdf"
