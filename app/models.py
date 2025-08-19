# app/models.py
from enum import Enum as PyEnum
from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, String, Enum, Boolean, DateTime, func, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
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
    customer_last_name:  Mapped[Optional[str]] = mapped_column(String(100))
    customer_phone_e164: Mapped[Optional[str]] = mapped_column(String(32))

    chat_id: Mapped[Optional[str]] = mapped_column(String(64))
    last_message_id: Mapped[Optional[int]] = mapped_column()

    raw_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

Index("ix_orders_status_created_at", Order.status, Order.created_at.desc())
