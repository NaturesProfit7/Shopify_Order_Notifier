# app/bot/main.py - С ИСПРАВЛЕННЫМ TIMEZONE
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import pytz

from app.db import get_session
from app.models import Order, OrderStatus

import logging

logger = logging.getLogger(__name__)


def get_timezone():
    """Получить правильную временную зону"""
    # Пробуем различные варианты названий для Киева
    timezone_variants = [
        "Europe/Kyiv",  # Новое официальное название
        "Europe/Kiev",  # Старое название
        "UTC"  # Fallback на UTC
    ]

    for tz_name in timezone_variants:
        try:
            return pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            continue

    # Если ничего не найдено - используем UTC
    logger.warning("Could not find Kyiv/Kiev timezone, using UTC")
    return pytz.UTC


class TelegramBot:
    """Singleton класс для управления Telegram ботом"""
    _instance: Optional['TelegramBot'] = None
    _lock = asyncio.Lock()

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

        self.bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

        # ИСПОЛЬЗУЕМ MemoryStorage для FSM
        storage = MemoryStorage()
        self.dp = Dispatcher(storage=storage)

        # ИСПРАВЛЕННЫЙ scheduler с правильным timezone
        self.timezone = get_timezone()
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        self.chat_id = os.getenv("TELEGRAM_TARGET_CHAT_ID")

        # Polling task
        self.polling_task: Optional[asyncio.Task] = None

        # Список разрешенных менеджеров
        allowed_ids = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        self.allowed_user_ids = [int(uid.strip()) for uid in allowed_ids.split(",") if uid.strip()]

        # Регистрируем хендлеры
        self._register_handlers()

        # Настраиваем планировщик
        self._setup_scheduler()

        self.initialized = True
        logger.info(f"TelegramBot initialized with timezone: {self.timezone}")

    def _register_handlers(self):
        """Регистрация всех хендлеров"""
        try:
            logger.info("Starting handler registration...")

            # Импортируем роутеры
            from app.bot.routers import commands, navigation, orders, management, test_commands, webhook

            logger.info("All routers imported successfully")

            # ИСПРАВЛЕННЫЙ ПОРЯДОК: специфические роутеры ПЕРЕД общими

            # 1. Management первым для FSM состояний
            self.dp.include_router(management.router)
            logger.info("✅ Management router registered (FSM priority)")

            # 2. Orders - обработка конкретных действий с заказами
            self.dp.include_router(orders.router)
            logger.info("✅ Orders router registered")

            # 3. Navigation - общая навигация
            self.dp.include_router(navigation.router)
            logger.info("✅ Navigation router registered")

            # 4. Commands - команды
            self.dp.include_router(commands.router)
            logger.info("✅ Commands router registered")

            # 5. Test commands
            self.dp.include_router(test_commands.router)
            logger.info("✅ Test commands router registered")

            # 6. Webhook ПОСЛЕДНИМ - только для кнопки "Закрити"
            self.dp.include_router(webhook.router)
            logger.info("✅ Webhook router registered (close button only)")

            logger.info("All handlers registered successfully!")

        except Exception as e:
            logger.error(f"Error registering handlers: {e}", exc_info=True)
            raise

    def _setup_scheduler(self):
        """Настройка планировщика задач"""
        # 1. Проверка НОВЫХ заказов КАЖДЫЙ ЧАС (10:00-22:00)
        self.scheduler.add_job(
            self._check_new_orders,
            trigger=IntervalTrigger(hours=1),
            id="check_new_orders",
            replace_existing=True
        )

        # 2. Проверка индивидуальных напоминаний каждые 5 минут
        self.scheduler.add_job(
            self._check_reminders,
            trigger=IntervalTrigger(minutes=5),
            id="check_reminders",
            replace_existing=True
        )

        # 3. Ежедневное напоминание об оплате в 10:30
        self.scheduler.add_job(
            self._check_payment_reminders,
            trigger=CronTrigger(hour=10, minute=30, timezone=self.timezone),
            id="payment_reminders",
            replace_existing=True
        )

        logger.info(f"Scheduler configured with timezone: {self.timezone}")

    def _is_working_hours(self) -> bool:
        """Проверка рабочего времени 10:00-22:00"""
        now_tz = datetime.now(self.timezone)
        hour = now_tz.hour

        return 10 <= hour < 22

    async def _check_new_orders(self):
        """Проверка заказов в статусе NEW - каждый час (10:00-22:00)"""
        try:
            # Проверяем рабочее время
            if not self._is_working_hours():
                logger.info("Skipping new orders check - outside working hours")
                return

            with get_session() as session:
                new_orders = session.query(Order).filter(
                    Order.status == OrderStatus.NEW
                ).order_by(Order.created_at.desc()).all()

                if not new_orders or not self.chat_id:
                    logger.info("No new orders to remind about")
                    return

                message = f"🆕 <b>Необроблені замовлення ({len(new_orders)} шт):</b>\n\n"

                for order in new_orders[:15]:
                    order_no = order.order_number or order.id
                    customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"

                    now_utc = datetime.utcnow()

                    if order.created_at.tzinfo is not None:
                        order_created_utc = order.created_at.astimezone(pytz.UTC).replace(tzinfo=None)
                    else:
                        order_created_utc = order.created_at

                    elapsed = now_utc - order_created_utc
                    hours = int(elapsed.total_seconds() // 3600)
                    minutes = int((elapsed.total_seconds() % 3600) // 60)

                    if hours >= 3:
                        urgency = "🚨"
                    elif hours >= 2:
                        urgency = "⚠️"
                    elif hours >= 1:
                        urgency = "🔥"
                    else:
                        urgency = "📍"

                    message += f"{urgency} №{order_no} • {customer}"

                    if hours > 0:
                        message += f" ({hours}г {minutes}хв тому)\n"
                    else:
                        message += f" ({minutes}хв тому)\n"

                if len(new_orders) > 15:
                    message += f"\n<i>...та ще {len(new_orders) - 15} замовлень</i>\n"

                message += f"\n🚀 <i>Час перетворити заявки в замовлення!</i>"

                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="📋 Переглянути необроблені",
                        callback_data="orders:list:new:offset=0"
                    )
                ]])

                await self.bot.send_message(
                    self.chat_id,
                    message,
                    reply_markup=keyboard
                )
                logger.info(f"Sent hourly NEW orders notification: {len(new_orders)} orders")

        except Exception as e:
            logger.error(f"Error checking new orders: {e}", exc_info=True)

    async def _check_payment_reminders(self):
        """Ежедневное напоминание об оплате в 10:30"""
        try:
            with get_session() as session:
                waiting_orders = session.query(Order).filter(
                    Order.status == OrderStatus.WAITING_PAYMENT
                ).order_by(Order.updated_at.desc()).all()

                if not waiting_orders or not self.chat_id:
                    logger.info("No payment reminders needed")
                    return

                message = f"💰 <b>Очікують оплату ({len(waiting_orders)} шт):</b>\n\n"

                for order in waiting_orders[:15]:
                    order_no = order.order_number or order.id
                    customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"

                    now_utc = datetime.utcnow()

                    if order.waiting_payment_since:
                        if order.waiting_payment_since.tzinfo is not None:
                            waiting_since_utc = order.waiting_payment_since.astimezone(pytz.UTC).replace(tzinfo=None)
                        else:
                            waiting_since_utc = order.waiting_payment_since
                    else:
                        if order.updated_at.tzinfo is not None:
                            waiting_since_utc = order.updated_at.astimezone(pytz.UTC).replace(tzinfo=None)
                        else:
                            waiting_since_utc = order.updated_at

                    elapsed = now_utc - waiting_since_utc
                    hours = int(elapsed.total_seconds() // 3600)
                    days = hours // 24

                    if days >= 2:
                        urgency = "🚨"
                    elif days >= 1:
                        urgency = "⚠️"
                    elif hours >= 12:
                        urgency = "🔥"
                    else:
                        urgency = "📍"

                    message += f"{urgency} №{order_no} • {customer}"

                    if days > 0:
                        message += f" ({days} дн.)\n"
                    elif hours > 0:
                        message += f" ({hours} год.)\n"
                    else:
                        message += " (сьогодні)\n"

                if len(waiting_orders) > 15:
                    message += f"\n<i>...та ще {len(waiting_orders) - 15} замовлень</i>\n"

                message += f"\n⚡ <i>Час закривати угоди!</i>"

                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="💳 Переглянути очікують оплату",
                        callback_data="orders:list:waiting:offset=0"
                    )
                ]])

                await self.bot.send_message(
                    self.chat_id,
                    message,
                    reply_markup=keyboard
                )
                logger.info(f"Sent daily PAYMENT reminders: {len(waiting_orders)} orders")

        except Exception as e:
            logger.error(f"Error checking payment reminders: {e}", exc_info=True)

    async def _check_reminders(self):
        """Проверка напоминаний о перезвоне - каждые 5 минут"""
        try:
            with get_session() as session:
                now = datetime.utcnow()
                reminders = session.query(Order).filter(
                    Order.reminder_at.isnot(None),
                    Order.reminder_at <= now
                ).limit(10).all()

                for order in reminders:
                    try:
                        order_no = order.order_number or order.id
                        customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"
                        phone = order.customer_phone_e164 if order.customer_phone_e164 else "Телефон відсутній"

                        message = (
                            f"🔔 <b>Нагадування про дзвінок!</b>\n\n"
                            f"📦 Замовлення №{order_no}\n"
                            f"👤 Клієнт: {customer}\n"
                            f"📱 Телефон: {phone}"
                        )

                        if order.comment:
                            message += f"\n💬 Коментар: <i>{order.comment}</i>"

                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(
                                text="📦 Відкрити замовлення",
                                callback_data=f"order:{order.id}:view"
                            )
                        ]])

                        if self.chat_id:
                            await self.bot.send_message(
                                self.chat_id,
                                message,
                                reply_markup=keyboard
                            )
                            logger.info(f"Sent reminder for order {order_no}")

                        order.reminder_at = None

                    except Exception as e:
                        logger.error(f"Error sending reminder for order {order.id}: {e}")

                session.commit()

        except Exception as e:
            logger.error(f"Error checking reminders: {e}", exc_info=True)

    async def start_polling(self):
        """Запуск polling в фоновой задаче"""
        try:
            logger.info("Starting bot polling...")

            if not self.scheduler.running:
                self.scheduler.start()
                logger.info("Scheduler started")

            await self.dp.start_polling(self.bot, allowed_updates=['message', 'callback_query'])

        except Exception as e:
            logger.error(f"Error in bot polling: {e}", exc_info=True)
            raise

    async def start(self):
        """Запуск бота в фоне (non-blocking)"""
        async with self._lock:
            if self.polling_task and not self.polling_task.done():
                logger.warning("Bot is already running")
                return

            self.polling_task = asyncio.create_task(self.start_polling())
            logger.info("Bot polling task created")

            await asyncio.sleep(1)

            try:
                me = await self.bot.get_me()
                logger.info(f"Bot started successfully: @{me.username}")
            except Exception as e:
                logger.error(f"Failed to start bot: {e}")
                if self.polling_task:
                    self.polling_task.cancel()
                raise

    async def stop(self):
        """Остановка бота"""
        async with self._lock:
            logger.info("Stopping Telegram bot...")

            try:
                if self.polling_task and not self.polling_task.done():
                    self.polling_task.cancel()
                    try:
                        await self.polling_task
                    except asyncio.CancelledError:
                        pass

                await self.dp.stop_polling()

                if self.scheduler.running:
                    self.scheduler.shutdown(wait=False)

                await self.bot.session.close()

                logger.info("Bot stopped successfully")

            except Exception as e:
                logger.error(f"Error stopping bot: {e}", exc_info=True)


# Глобальный экземпляр бота
_bot_instance: Optional[TelegramBot] = None


def get_bot_instance() -> TelegramBot:
    """Получить или создать экземпляр бота"""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = TelegramBot()
    return _bot_instance


async def start_bot():
    """Функция для запуска бота из FastAPI lifespan"""
    bot = get_bot_instance()
    await bot.start()


async def stop_bot():
    """Функция для остановки бота"""
    global _bot_instance
    if _bot_instance:
        await _bot_instance.stop()
        _bot_instance = None


def get_bot() -> Optional[Bot]:
    """Получить экземпляр Bot для отправки сообщений"""
    instance = get_bot_instance()
    return instance.bot if instance else None