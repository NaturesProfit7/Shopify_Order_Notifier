"""add comments and reminders

Revision ID: b123456789ab
Revises: a02534ff18f5
Create Date: 2025-01-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'b123456789ab'
down_revision = 'a02534ff18f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем новые колонки в таблицу orders
    op.add_column('orders', sa.Column('comment', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('reminder_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('last_reminder_sent', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('processed_by_user_id', sa.BigInteger(), nullable=True))
    op.add_column('orders', sa.Column('processed_by_username', sa.String(100), nullable=True))

    # Создаем таблицу для истории изменений
    op.create_table('order_status_history',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('order_id', sa.BigInteger(), nullable=False),
                    sa.Column('old_status', sa.String(50), nullable=True),
                    sa.Column('new_status', sa.String(50), nullable=False),
                    sa.Column('changed_by_user_id', sa.BigInteger(), nullable=True),
                    sa.Column('changed_by_username', sa.String(100), nullable=True),
                    sa.Column('comment', sa.Text(), nullable=True),
                    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                              nullable=False),
                    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
                    )

    op.create_index('ix_order_status_history_order_id', 'order_status_history', ['order_id'])


def downgrade() -> None:
    op.drop_index('ix_order_status_history_order_id', table_name='order_status_history')
    op.drop_table('order_status_history')

    op.drop_column('orders', 'processed_by_username')
    op.drop_column('orders', 'processed_by_user_id')
    op.drop_column('orders', 'last_reminder_sent')
    op.drop_column('orders', 'reminder_at')
    op.drop_column('orders', 'comment')