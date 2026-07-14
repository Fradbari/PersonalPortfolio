"""category_raw + category_pending (Fase F1, ADR-0013 punti 4 e 5)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `transactions` è ancora vuota in questa fase (nessun dato reale importato):
    # NOT NULL diretto senza server_default temporaneo/backfill.
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("category_raw", sa.String, nullable=False))

    op.create_table(
        "category_pending",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String, nullable=False),       # master_sheet | my_finance
        sa.Column("source_name", sa.String, nullable=False),  # nome categoria as-is dalla fonte
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("source", "source_name", name="uq_pending_source_name"),
    )


def downgrade() -> None:
    op.drop_table("category_pending")

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("category_raw")
