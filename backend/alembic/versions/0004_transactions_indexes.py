"""Indici su transactions per filtri avanzati (Fase F12, ADR-0029)

Indici su date, account, category_id, type per supportare i filtri introdotti in F12.
Questo è l'ultimo cambio di schema su `transactions` prima di F12 (T3) che aggiungerà
FTS5 con trigger: qualunque ALTER dopo droppa i trigger silenziosamente (D4).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_transactions_date", "transactions", ["date"])
    op.create_index("idx_transactions_account", "transactions", ["account"])
    op.create_index("idx_transactions_category_id", "transactions", ["category_id"])
    op.create_index("idx_transactions_type", "transactions", ["type"])


def downgrade() -> None:
    op.drop_index("idx_transactions_type")
    op.drop_index("idx_transactions_category_id")
    op.drop_index("idx_transactions_account")
    op.drop_index("idx_transactions_date")
