# app/models.py
from enum import Enum as PyEnum
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Boolean, DateTime, func, Index, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base


class OrderStatus(PyEnum):
    NEW = "NEW"
    WAITING_PAYMENT = "WAITING_PAYMENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Shopify order_id
    order_number: Mapped[Optional[str]] = mapped_column(String(32))

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"),
        default=OrderStatus.NEW, nullable=False
    )
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    customer_first_name: Mapped[Optional[str]] = mapped_column(String(100))
    customer_last_name: Mapped[Optional[str]] = mapped_column(String(100))
    customer_phone_e164: Mapped[Optional[str]] = mapped_column(String(32))

    chat_id: Mapped[Optional[str]] = mapped_column(String(64))
    last_message_id: Mapped[Optional[int]] = mapped_column()

    # Новые поля
    comment: Mapped[Optional[str]] = mapped_column(Text)
    reminder_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_reminder_sent: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    processed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    processed_by_username: Mapped[Optional[str]] = mapped_column(String(100))

    raw_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Связь с историей
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


Index("ix_orders_status_created_at", Order.status, Order.created_at.desc())


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"))

    old_status: Mapped[Optional[str]] = mapped_column(String(50))
    new_status: Mapped[str] = mapped_column(String(50))

    changed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    changed_by_username: Mapped[Optional[str]] = mapped_column(String(100))
    comment: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped["Order"] = relationship(back_populates="status_history")