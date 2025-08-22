"""add waiting_payment_since field

Revision ID: c123456789ab
Revises: b123456789ab  # ← ИЗМЕНИТЕ на ваш последний revision
Create Date: 2025-01-08 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'c123456789ab'  # ← alembic сгенерирует свой ID
down_revision = 'b123456789ab'  # ← ИЗМЕНИТЕ на ваш последний revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле для отслеживания времени перехода в WAITING_PAYMENT
    op.add_column('orders', sa.Column('waiting_payment_since', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'waiting_payment_since')