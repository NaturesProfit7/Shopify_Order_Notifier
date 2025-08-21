# app/bot/main.py
import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional
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

        self.bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()
        self.scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
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
        logger.info("TelegramBot initialized")

    def _register_handlers(self):
        """Регистрация всех хендлеров"""
        self.dp.include_router(commands.router)
        self.dp.include_router(callbacks.router)
        logger.info("Handlers registered")

    def _setup_scheduler(self):
        """Настройка планировщика задач"""
        # Проверка НОВЫХ заказов КАЖДЫЙ ЧАС
        self.scheduler.add_job(
            self._check_new_orders,
            trigger=IntervalTrigger(hours=1),  # Изменено с 30 минут на 1 час
            id="check_new_orders",
            replace_existing=True
        )

        # Проверка напоминаний каждые 5 минут (оставляем как есть)
        self.scheduler.add_job(
            self._check_reminders,
            trigger=IntervalTrigger(minutes=5),
            id="check_reminders",
            replace_existing=True
        )
        logger.info("Scheduler configured: check new orders every hour, check reminders every 5 min")

    async def _check_new_orders(self):
        """Проверка заказов в статусе NEW - каждый час"""
        try:
            with get_session() as session:
                # Находим ВСЕ заказы в статусе NEW
                new_orders = session.query(Order).filter(
                    Order.status == OrderStatus.NEW
                ).order_by(Order.created_at.desc()).all()

                # Если нет новых заказов - не отправляем уведомление
                if not new_orders or not self.chat_id:
                    return

                # Формируем сообщение
                message = f"🆕 <b>Необроблені замовлення ({len(new_orders)} шт):</b>\n\n"

                for order in new_orders[:10]:  # Показываем первые 10
                    order_no = order.order_number or order.id
                    customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip() or "Без імені"

                    # Рассчитываем время с момента создания
                    elapsed = datetime.utcnow() - order.created_at
                    hours = int(elapsed.total_seconds() // 3600)
                    minutes = int((elapsed.total_seconds() % 3600) // 60)

                    # Добавляем индикатор срочности
                    if hours >= 2:
                        urgency = "🔥"  # Срочно - более 2 часов
                    elif hours >= 1:
                        urgency = "⚠️"  # Внимание - более часа
                    else:
                        urgency = "📍"  # Обычный

                    message += f"{urgency} №{order_no} • {customer}"

                    # Показываем время
                    if hours > 0:
                        message += f" ({hours}г {minutes}хв тому)\n"
                    else:
                        message += f" ({minutes}хв тому)\n"

                if len(new_orders) > 10:
                    message += f"\n<i>...та ще {len(new_orders) - 10} замовлень</i>\n"

                # Добавляем кнопку для быстрого перехода
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="📋 Переглянути необроблені",
                        callback_data="orders:list:pending:offset=0"
                    )
                ]])

                # Отправляем уведомление
                await self.bot.send_message(
                    self.chat_id,
                    message,
                    reply_markup=keyboard
                )
                logger.info(f"Sent hourly notification for {len(new_orders)} new orders")

        except Exception as e:
            logger.error(f"Error checking new orders: {e}", exc_info=True)

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
                    (Order.last_reminder_sent < datetime.utcnow() - timedelta(hours=2))
                ).limit(5).all()

                if unprocessed and self.chat_id:
                    message = "⚠️ <b>Необроблені замовлення (30+ хв):</b>\n\n"
                    for order in unprocessed:
                        order_no = order.order_number or order.id
                        customer = f"{order.customer_first_name or ''} {order.customer_last_name or ''}".strip()
                        elapsed = datetime.utcnow() - order.created_at
                        hours = int(elapsed.total_seconds() // 3600)
                        minutes = int((elapsed.total_seconds() % 3600) // 60)

                        message += f"• №{order_no} - {customer or 'Без імені'}"
                        if hours > 0:
                            message += f" ({hours}г {minutes}хв тому)\n"
                        else:
                            message += f" ({minutes}хв тому)\n"

                        # Обновляем время последнего напоминания
                        order.last_reminder_sent = datetime.utcnow()

                    session.commit()

                    # Отправляем уведомление
                    await self.bot.send_message(self.chat_id, message)
                    logger.info(f"Sent reminder for {len(unprocessed)} unprocessed orders")

        except Exception as e:
            logger.error(f"Error checking unprocessed orders: {e}", exc_info=True)

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

                        # Форматируем телефон БЕЗ пробелов
                        phone = order.customer_phone_e164 if order.customer_phone_e164 else "Телефон відсутній"

                        message = (
                            f"🔔 <b>Нагадування про дзвінок!</b>\n\n"
                            f"📦 Замовлення №{order_no}\n"
                            f"👤 Клієнт: {customer}\n"
                            f"📱 Телефон: {phone}"
                        )

                        if order.comment:
                            message += f"\n💬 Коментар: <i>{order.comment}</i>"

                        # Добавляем кнопку для перехода к заказу
                        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(
                                text="📦 Відкрити замовлення",
                                callback_data=f"order:{order.id}:view"
                            )
                        ]])

                        # Отправляем напоминание
                        if self.chat_id:
                            await self.bot.send_message(
                                self.chat_id,
                                message,
                                reply_markup=keyboard
                            )
                            logger.info(f"Sent reminder for order {order_no}")

                        # Очищаем напоминание
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

            # Запускаем планировщик
            if not self.scheduler.running:
                self.scheduler.start()
                logger.info("Scheduler started")

            # Запускаем polling
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

            # Создаем фоновую задачу для polling
            self.polling_task = asyncio.create_task(self.start_polling())
            logger.info("Bot polling task created")

            # Даем время на инициализацию
            await asyncio.sleep(1)

            # Проверяем, что бот запустился
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
                # Останавливаем polling
                if self.polling_task and not self.polling_task.done():
                    self.polling_task.cancel()
                    try:
                        await self.polling_task
                    except asyncio.CancelledError:
                        pass

                # Останавливаем диспетчер
                await self.dp.stop_polling()

                # Останавливаем планировщик
                if self.scheduler.running:
                    self.scheduler.shutdown(wait=False)

                # Закрываем сессию бота
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