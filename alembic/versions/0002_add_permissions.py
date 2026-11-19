"""add permissions + role_permissions

Revision ID: 0002_add_permissions
Revises: 0001_init_auth
Create Date: auto-generated
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_permissions"
down_revision = "0001_init_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.String(255), nullable=True),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(),
                  sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", sa.Integer(),
                  sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    )
    # Данные заполняются при старте приложения (seed_permissions),
    # чтобы избежать дублирования списка прав в коде и в миграции.


def downgrade() -> None:
    op.drop_table("role_permissions")
    op.drop_table("permissions")
