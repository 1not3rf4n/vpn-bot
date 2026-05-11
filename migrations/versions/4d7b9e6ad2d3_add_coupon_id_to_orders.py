"""Add coupon_id to orders

Revision ID: 4d7b9e6ad2d3
Revises: 9f1b2c0d8a11
Create Date: 2026-05-11

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d7b9e6ad2d3"
down_revision: Union[str, Sequence[str], None] = "9f1b2c0d8a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("coupon_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "coupon_id")

