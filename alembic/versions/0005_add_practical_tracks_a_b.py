"""Add promo codes, loyalty ledger and order amounts for practical tracks A/B.

Revision ID: 0005_add_practical_tracks_a_b
Revises: 0004_add_event_tables
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_add_practical_tracks_a_b"
down_revision = "0004_add_event_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("discount_type", sa.String(10), nullable=False),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_until", sa.DateTime(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("current_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_order_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("discount_type IN ('percent', 'fixed')", name="ck_promo_discount_type"),
        sa.CheckConstraint("discount_value > 0", name="ck_promo_discount_positive"),
        sa.CheckConstraint("current_uses >= 0", name="ck_promo_current_uses_nonnegative"),
    )
    op.add_column("orders", sa.Column("total_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("orders", sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("promo_code_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("points_spent", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.create_foreign_key("fk_orders_promo_code_id", "orders", "promo_codes", ["promo_code_id"], ["id"])

    op.create_table(
        "promo_code_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("promo_code_id", sa.Integer(), sa.ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("used_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("promo_code_id", "user_id", name="uq_promo_code_user_usage"),
    )
    op.create_table(
        "promo_code_compensations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("compensation_key", sa.String(100), nullable=False, unique=True),
        sa.Column("promo_code_id", sa.Integer(), sa.ForeignKey("promo_codes.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "loyalty_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("balance", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_earned", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tier", sa.String(10), nullable=False, server_default="Bronze"),
        sa.CheckConstraint("balance >= 0", name="ck_loyalty_balance_nonnegative"),
        sa.CheckConstraint("total_earned >= 0", name="ck_loyalty_total_earned_nonnegative"),
    )
    op.create_table(
        "loyalty_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("type IN ('earn', 'spend', 'refund', 'revoke')", name="ck_loyalty_transaction_type"),
    )
    op.create_index("ix_loyalty_transactions_order_id", "loyalty_transactions", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_loyalty_transactions_order_id", table_name="loyalty_transactions")
    op.drop_table("loyalty_transactions")
    op.drop_table("loyalty_accounts")
    op.drop_table("promo_code_compensations")
    op.drop_table("promo_code_usages")
    op.drop_constraint("fk_orders_promo_code_id", "orders", type_="foreignkey")
    op.drop_column("orders", "points_spent")
    op.drop_column("orders", "promo_code_id")
    op.drop_column("orders", "discount_amount")
    op.drop_column("orders", "total_amount")
    op.drop_table("promo_codes")
