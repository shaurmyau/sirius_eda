"""add category to menu_items

Revision ID: 0003_add_menu_category
Revises: 0002_add_permissions
Create Date: auto-generated
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_add_menu_category"
down_revision = "0002_add_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column("category", sa.String(50), nullable=False,
                  server_default="food"),
    )
    op.create_check_constraint(
        "ck_menu_items_category",
        "menu_items",
        "category IN ('food', 'drink', 'other')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_menu_items_category", "menu_items", type_="check")
    op.drop_column("menu_items", "category")
