"""orders table

Revision ID: a02534ff18f5
Revises:
Create Date: 2025-08-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Идентификаторы ревизии
revision = "a02534ff18f5"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Объявляем диалектный ENUM и создаём его один раз (если ещё нет)
    status_enum = postgresql.ENUM(
        "NEW", "WAITING_PAYMENT", "PAID", "CANCELLED",
        name="order_status",
        create_type=True,   # позволяем создавать здесь
    )
    status_enum.create(bind, checkfirst=True)  # безопасно: не создаст, если уже есть

    # 2) Таблица orders. В колонке используем Тот Же тип, но
    #    запрещаем автосоздание типа во время create_table.
    status_enum_for_column = postgresql.ENUM(
        "NEW", "WAITING_PAYMENT", "PAID", "CANCELLED",
        name="order_status",
        create_type=False,   # не создавать второй раз при создании таблицы
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True, nullable=False),  # Shopify order_id
        sa.Column("order_number", sa.String(length=32), nullable=True),

        sa.Column("status", status_enum_for_column, nullable=False, server_default="NEW"),
        sa.Column("is_processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),

        sa.Column("customer_first_name", sa.String(length=100), nullable=True),
        sa.Column("customer_last_name", sa.String(length=100), nullable=True),
        sa.Column("customer_phone_e164", sa.String(length=32), nullable=True),

        sa.Column("chat_id", sa.String(length=64), nullable=True),
        sa.Column("last_message_id", sa.Integer(), nullable=True),

        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index(
        "ix_orders_status_created_at",
        "orders",
        ["status", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    # Снимаем индекс и удаляем таблицу
    op.drop_index("ix_orders_status_created_at", table_name="orders")
    op.drop_table("orders")

    # А затем удаляем сам тип (если больше нигде не используется)
    bind = op.get_bind()
    status_enum = postgresql.ENUM(
        "NEW", "WAITING_PAYMENT", "PAID", "CANCELLED",
        name="order_status",
        create_type=False,
    )
    status_enum.drop(bind, checkfirst=True)
