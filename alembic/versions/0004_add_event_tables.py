"""add processed_events and kitchen_orders (event-driven, ЛР № 7)

Revision ID: 0004_add_event_tables
Revises: 0003_add_menu_category
Create Date: auto-generated

Миграция защищена от повторного применения: если таблицы уже созданы
(например, через Base.metadata.create_all), они пропускаются.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_add_event_tables"
down_revision = "0003_add_menu_category"
branch_labels = None
depends_on = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing_tables()
    if "processed_events" not in existing:
        op.create_table(
            "processed_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.String(64), nullable=False),
            sa.Column("consumer", sa.String(50), nullable=False),
            sa.Column("processed_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("event_id", "consumer",
                                name="uq_processed_events_event_consumer"),
        )
    if "kitchen_orders" not in existing:
        op.create_table(
            "kitchen_orders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"),
                      nullable=False, unique=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade() -> None:
    existing = _existing_tables()
    if "kitchen_orders" in existing:
        op.drop_table("kitchen_orders")
    if "processed_events" in existing:
        op.drop_table("processed_events")
