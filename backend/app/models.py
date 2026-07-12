"""Schema canonico base (Fase 0).

NOTA: `category_pending` (F1) e `settings` (F4) sono aggiunte in fasi successive
tramite Alembic revision dedicate (ADR-0003), non qui.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Category(Base):
    """Categoria canonica (tassonomia unica)."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class CategoryMap(Base):
    """Mappa nome-sorgente -> categoria canonica (ADR-0006)."""
    __tablename__ = "category_map"
    __table_args__ = (UniqueConstraint("source", "source_name", name="uq_source_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)       # master_sheet | my_finance
    source_name: Mapped[str] = mapped_column(String, nullable=False)  # nome categoria nella fonte
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)


class Account(Base):
    """Conto importato as-is (ADR-0006). Rinominabile via display_name."""
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)


class ImportBatch(Base):
    """Audit di ogni import (idempotenza, tracciabilità)."""
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)     # master_sheet | my_finance
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="completed")

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="batch")


class Transaction(Base):
    """Transazione canonica a livello riga.

    `type` a 2 valori: bonifici esclusi (ADR-0007).
    `hash_dedup` = hash di (date@giorno, amount, category, account, type) — ADR-0005.
    """
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("type IN ('expense','income')", name="ck_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, default="EUR")
    type: Mapped[str] = mapped_column(String, nullable=False)  # expense | income
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    account: Mapped[str] = mapped_column(String, default="principale")
    comment: Mapped[str | None] = mapped_column(String, nullable=True)  # editabile: NON nell'hash
    tag: Mapped[str | None] = mapped_column(String, nullable=True)      # editabile: NON nell'hash
    source: Mapped[str] = mapped_column(String, nullable=False)         # master_sheet | my_finance
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    hash_dedup: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    batch: Mapped["ImportBatch"] = relationship(back_populates="transactions")
