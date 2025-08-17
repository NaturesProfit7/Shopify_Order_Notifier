# app/services/pdf_service.py
from __future__ import annotations
from io import BytesIO
from datetime import datetime
from typing import Tuple
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FNT_REGULAR = "DejaVuSans"
FNT_BOLD = "DejaVuSans-Bold"

def _register_fonts():
    """Регистрируем DejaVu Sans; если файлов нет — остаёмся на Helvetica."""
    try:
        base = Path(__file__).resolve().parents[1] / "assets" / "fonts"
        pdfmetrics.registerFont(TTFont(FNT_REGULAR, str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont(FNT_BOLD, str(base / "DejaVuSans-Bold.ttf")))
        return True
    except Exception:
        return False

def _fmt_date(dt_str: str | None) -> str:
    if not dt_str:
        return datetime.now().strftime("%d.%m.%Y %H:%M")
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return datetime.now().strftime("%d.%m.%Y %H:%M")

def _full_name(order: dict) -> str:
    cust = (order.get("customer") or {})
    first = (cust.get("first_name") or "").strip()
    last  = (cust.get("last_name") or "").strip()
    if not (first or last):
        ship = (order.get("shipping_address") or {})
        first = (ship.get("first_name") or "").strip() or first
        last  = (ship.get("last_name") or "").strip() or last
    if not (first or last):
        bill = (order.get("billing_address") or {})
        first = (bill.get("first_name") or "").strip() or first
        last  = (bill.get("last_name") or "").strip() or last
    return f"{first} {last}".strip() or "—"

def _address(order: dict) -> str:
    ship = (order.get("shipping_address") or {})
    parts = [ship.get("address1") or "", ship.get("address2") or "", ship.get("city") or "", ship.get("zip") or "", ship.get("country") or ""]
    return ", ".join([p for p in parts if p]).strip() or "—"

def build_order_pdf(order: dict) -> Tuple[bytes, str]:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    has_fonts = _register_fonts()

    order_no = order.get("order_number") or order.get("id") or "—"
    created  = _fmt_date(order.get("created_at"))
    name     = _full_name(order)
    addr     = _address(order)

    top = height - 20*mm
    x0  = 20*mm

    title_font = FNT_BOLD if has_fonts else "Helvetica-Bold"
    text_font  = FNT_REGULAR if has_fonts else "Helvetica"

    c.setTitle(f"Замовлення #{order_no}")
    c.setFont(title_font, 16)
    c.drawString(x0, top, f"Замовлення № {order_no}")

    c.setFont(text_font, 11)
    line_y = top - 10*mm
    c.drawString(x0, line_y, f"Дата: {created}")
    line_y -= 7*mm
    c.drawString(x0, line_y, f"Клієнт: {name}")
    line_y -= 7*mm
    c.drawString(x0, line_y, f"Адреса: {addr}")

    line_y -= 12*mm
    c.setFont(title_font, 12)
    c.drawString(x0, line_y, "Товари")
    line_y -= 7*mm

    c.setFont(title_font, 10)
    c.drawString(x0, line_y, "Назва")
    c.drawString(x0 + 110*mm, line_y, "К-ть")
    c.drawString(x0 + 130*mm, line_y, "Ціна, грн")
    c.drawString(x0 + 160*mm, line_y, "Сума, грн")

    c.setFont(text_font, 10)
    line_y -= 5*mm
    c.line(x0, line_y, width - x0, line_y)
    line_y -= 6*mm

    subtotal = 0.0
    line_items = order.get("line_items") or []
    for item in line_items:
        title = str(item.get("title") or "—")
        qty   = int(item.get("quantity") or 0)
        price = float(item.get("price") or 0.0)
        total = qty * price
        subtotal += total

        # наивный перенос строк
        max_chars = 60
        while title:
            part, title = title[:max_chars], title[max_chars:]
            c.drawString(x0 + (5*mm if part != title[:max_chars] else 0), line_y, part)
            if part == part:  # первая строка позиции
                c.drawRightString(x0 + 125*mm, line_y, str(qty))
                c.drawRightString(x0 + 155*mm, line_y, f"{price:,.2f}".replace(",", " "))
                c.drawRightString(x0 + 185*mm, line_y, f"{total:,.2f}".replace(",", " "))
            line_y -= 6*mm
            if line_y < 25*mm:
                c.showPage()
                c.setFont(text_font, 10)
                line_y = height - 20*mm

        line_y -= 2*mm

    line_y -= 4*mm
    c.setFont(title_font, 11)
    c.drawRightString(x0 + 185*mm, line_y, f"Разом: {subtotal:,.2f} грн".replace(",", " "))

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()

    return pdf_bytes, f"order_#{order_no}.pdf"
