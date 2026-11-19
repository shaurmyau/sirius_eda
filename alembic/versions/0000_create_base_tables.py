"""create base tables (users, menu_items, orders, deliveries)

Revision ID: 0000_create_base_tables
Revises:
Create Date: auto-generated
"""
from alembic import op
import sqlalchemy as sa

revision = "0000_create_base_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("balance", sa.Float(), server_default="0"),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false")),
    )
    op.create_index("ix_users_id", "users", ["id"])

    op.create_table(
        "menu_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true")),
    )
    op.create_index("ix_menu_items_id", "menu_items", ["id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("menu_items.id")),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), server_default="processing"),
    )
    op.create_index("ix_orders_id", "orders", ["id"])

    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(), server_default="pending"),
    )
    op.create_index("ix_deliveries_id", "deliveries", ["id"])


def downgrade() -> None:
    op.drop_table("deliveries")
    op.drop_table("orders")
    op.drop_table("menu_items")
    op.drop_table("users")
