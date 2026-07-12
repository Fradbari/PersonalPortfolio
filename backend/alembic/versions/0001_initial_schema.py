"""initial base schema (Fase 0)

Revision ID: 0001
Revises:
Create Date: 2026-07-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
    )
    op.create_table(
        "category_map",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("source_name", sa.String, nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=False),
        sa.UniqueConstraint("source", "source_name", name="uq_source_name"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("display_name", sa.String, nullable=True),
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("filename", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("status", sa.String, nullable=True),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.DateTime, nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("currency", sa.String, nullable=True),
        sa.Column("type", sa.String, nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("account", sa.String, nullable=True),
        sa.Column("comment", sa.String, nullable=True),
        sa.Column("tag", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("import_batch_id", sa.Integer, sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("hash_dedup", sa.String, nullable=False, unique=True),
        sa.CheckConstraint("type IN ('expense','income')", name="ck_type"),
    )


def downgrade() -> None:
    op.drop_table("transactions")
    op.drop_table("import_batches")
    op.drop_table("accounts")
    op.drop_table("category_map")
    op.drop_table("categories")
