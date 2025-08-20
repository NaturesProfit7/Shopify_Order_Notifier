# app/bot/main.py
import asyncio
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.bot.routers import commands, callbacks
from app.db import get_session
from app.models import Order, OrderStatus

import logging

logger = logging.getLogger(__name__)


class TelegramBot:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, 'initialized'):
            return

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

        self.bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()
        self.scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
        self.chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")

        # Список разрешенных менеджеров
        allowed_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        self.allowed_user_ids = [int(uid.strip()) for uid in allowed_ids.split(",") if uid.strip()]

        # Регистрируем хендлеры
        self._register_handlers()

        # Настраиваем планировщик
        self._setup_scheduler()

        self.initialized = True

    def _register_handlers(self):
        """Регистрация всех хендлеров"""
        self.dp.include_router(commands.router)
        self.dp.include_router(callbacks.router)

    def _setup_scheduler(self):
        """Настройка планировщика задач"""
        # Проверка необработанных заказов каждые 30 минут
        self.scheduler.add_job(
            self._check_unprocessed_orders,
            trigger=IntervalTrigger(minutes=30),
            id="check_unprocessed",
            replace_existing=True
        )

        # Проверка напоминаний каждые 5 минут
        self.scheduler.add_job(
            self._check_reminders,
            trigger=IntervalTrigger(minutes=5),
            id="check_reminders",
            replace_existing=True
        )

    async def _check_unprocessed_orders(self):
        """Проверка необработанных заказов"""
        try:
            with get_session() as session:
                # Заказы старше 30 минут в статусе NEW
                threshold = datetime.utcnow() - timedelta(minutes=30)
                unprocessed = session.query(Order).filter(
                    Order.status == OrderStatus.NEW,
                    Order.created_at < threshold,
                    (Order.last_reminder_sent.is_(None)) |
                    (Order.last_reminder_sent < datetime.utcnow() - timedelta(minutes=30))
                ).all()

                if unprocessed:
                    message = "⚠️ <b>Необроблені замовлення:</b>\n\n"
                    for order in unprocessed:
                        order_no = order.order_number or order.id
                        customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip()
                        message += f"• №{order_no} - {customer or 'Без імені'}\n"

                        # Обновляем время последнего напоминания
                        order.last_reminder_sent = datetime.utcnow()

                    session.commit()

                    # Отправляем уведомление
                    await self.bot.send_message(self.chat_id, message)

        except Exception as e:
            logger.error(f"Error checking unprocessed orders: {e}")

    async def _check_reminders(self):
        """Проверка напоминаний о перезвоне"""
        try:
            with get_session() as session:
                now = datetime.utcnow()
                reminders = session.query(Order).filter(
                    Order.reminder_at.isnot(None),
                    Order.reminder_at <= now
                ).all()

                for order in reminders:
                    order_no = order.order_number or order.id
                    customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip()
                    phone = order.customer_phone_e164 or "Телефон відсутній"

                    message = (
                        f"🔔 <b>Нагадування про дзвінок!</b>\n\n"
                        f"Замовлення №{order_no}\n"
                        f"Клієнт: {customer or 'Без імені'}\n"
                        f"Телефон: {phone}"
                    )

                    if order.comment:
                        message += f"\n\n💬 Коментар: {order.comment}"

                    # Отправляем напоминание
                    await self.bot.send_message(self.chat_id, message)

                    # Очищаем напоминание
                    order.reminder_at = None
                    session.commit()

        except Exception as e:
            logger.error(f"Error checking reminders: {e}")

    async def start(self):
        """Запуск бота"""
        logger.info("Starting Telegram bot...")

        # Запускаем планировщик
        self.scheduler.start()

        # Запускаем polling
        await self.dp.start_polling(self.bot)

    async def stop(self):
        """Остановка бота"""
        logger.info("Stopping Telegram bot...")

        # Останавливаем планировщик
        self.scheduler.shutdown(wait=True)

        # Останавливаем polling
        await self.dp.stop_polling()

        # Закрываем соединение бота
        await self.bot.session.close()


# Глобальный экземпляр бота
bot_instance: TelegramBot = None


def get_bot_instance() -> TelegramBot:
    """Получить или создать экземпляр бота"""
    global bot_instance
    if bot_instance is None:
        bot_instance = TelegramBot()
    return bot_instance


async def start_bot():
    """Функция для запуска бота из FastAPI"""
    bot = get_bot_instance()
    await bot.start()


async def stop_bot():
    """Функция для остановки бота"""
    global bot_instance
    if bot_instance:
        await bot_instance.stop()
        bot_instance = None


def get_bot() -> Bot:
    """Получить экземпляр Bot для отправки сообщений"""
    instance = get_bot_instance()
    return instance.bot if instance else None