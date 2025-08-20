# app/bot/handlers/commands.py
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.db import get_session
from app.models import Order, OrderStatus
from datetime import datetime, timedelta

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    await message.answer(
        "👋 Вітаю! Я бот для управління замовленнями.\n\n"
        "Доступні команди:\n"
        "/stats - статистика замовлень\n"
        "/pending - необроблені замовлення\n"
        "/today - замовлення за сьогодні"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Статистика заказов"""
    with get_session() as session:
        total = session.query(Order).count()
        new = session.query(Order).filter(Order.status == OrderStatus.NEW).count()
        waiting = session.query(Order).filter(Order.status == OrderStatus.WAITING_PAYMENT).count()
        paid = session.query(Order).filter(Order.status == OrderStatus.PAID).count()
        cancelled = session.query(Order).filter(Order.status == OrderStatus.CANCELLED).count()

        stats_text = f"""
📊 <b>Статистика замовлень:</b>

Всього: {total}
🆕 Нових: {new}
⏳ Очікують оплату: {waiting}
✅ Оплачених: {paid}
❌ Скасованих: {cancelled}
"""

        await message.answer(stats_text)


@router.message(Command("pending"))
async def cmd_pending(message: Message):
    """Список необработанных заказов"""
    with get_session() as session:
        orders = session.query(Order).filter(
            Order.status.in_([OrderStatus.NEW, OrderStatus.WAITING_PAYMENT])
        ).order_by(Order.created_at.desc()).limit(10).all()

        if not orders:
            await message.answer("✨ Всі замовлення оброблені!")
            return

        text = "📋 <b>Необроблені замовлення:</b>\n\n"
        for order in orders:
            order_no = order.order_number or order.id
            customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip()
            status = "🆕 Новий" if order.status == OrderStatus.NEW else "⏳ Очікує оплату"
            text += f"• №{order_no} - {customer or 'Без імені'} - {status}\n"

        await message.answer(text)


@router.message(Command("today"))
async def cmd_today(message: Message):
    """Заказы за сегодня"""
    with get_session() as session:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        orders = session.query(Order).filter(
            Order.created_at >= today
        ).order_by(Order.created_at.desc()).all()

        if not orders:
            await message.answer("📭 Сьогодні замовлень ще не було")
            return

        text = f"📅 <b>Замовлення за сьогодні ({len(orders)} шт):</b>\n\n"

        for order in orders[:15]:  # Показываем первые 15
            order_no = order.order_number or order.id
            customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip()
            status_emoji = {
                OrderStatus.NEW: "🆕",
                OrderStatus.WAITING_PAYMENT: "⏳",
                OrderStatus.PAID: "✅",
                OrderStatus.CANCELLED: "❌"
            }.get(order.status, "")

            text += f"{status_emoji} №{order_no} - {customer or 'Без імені'}\n"

        if len(orders) > 15:
            text += f"\n<i>...та ще {len(orders) - 15} замовлень</i>"

        await message.answer(text)