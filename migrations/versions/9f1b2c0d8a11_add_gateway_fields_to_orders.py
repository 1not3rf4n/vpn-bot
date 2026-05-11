"""Add gateway fields to orders

Revision ID: 9f1b2c0d8a11
Revises: 0cdb203b547a
Create Date: 2026-05-11

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f1b2c0d8a11"
down_revision: Union[str, Sequence[str], None] = "0cdb203b547a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("gateway_authority", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("gateway_tracking_id", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("gateway_hash_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "gateway_hash_id")
    op.drop_column("orders", "gateway_tracking_id")
    op.drop_column("orders", "gateway_authority")

