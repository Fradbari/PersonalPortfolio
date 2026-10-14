"""transactions_fts FTS5 + 3 trigger di sincronizzazione (Fase F12, ADR-0029)

Tabella virtuale FTS5 a contenuto esterno (content='transactions', content_rowid='id')
su comment/tag/category_raw/account, con tre trigger AFTER INSERT/UPDATE/DELETE che
tengono l'indice sincronizzato (FastAPI e' l'unico writer, ADR-0001 -> i trigger sono
l'unico punto di sincronizzazione necessario). Popolamento iniziale con il comando
speciale 'rebuild' in coda all'upgrade, cosi' le righe gia' esistenti in transactions
entrano subito nell'indice.

SOLO `op.execute()` SQL raw in questo file, MAI `batch_alter_table`/ricreazione tabella:
un ALTER via batch su `transactions` ricostruisce la tabella (rename->create->copy->drop)
e droppa silenziosamente questi trigger nello stesso momento in cui vengono creati (D4,
verificato empiricamente con Alembic 1.14.0 in T3). Questa e' quindi l'ULTIMA migration
del blocco che tocca lo schema di `transactions` in qualunque forma (vedi 0004): da qui
in poi nessun'altra migration fa ALTER/ricreazione su questa tabella.

Trasformazione dei valori: RAW (nessun COALESCE), identica nei tre trigger e coerente con
il comando 'rebuild' (che legge le colonne della content table cosi' come sono, incluso
NULL su comment/tag che sono nullable in models.py). Verificato empiricamente che NULL su
comment/tag non fa fallire 'integrity-check', ne' prima ne' dopo UPDATE (D6).

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIRTUAL TABLE transactions_fts USING fts5(
            comment, tag, category_raw, account,
            content='transactions', content_rowid='id'
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_transactions_fts_insert AFTER INSERT ON transactions BEGIN
            INSERT INTO transactions_fts(rowid, comment, tag, category_raw, account)
            VALUES (new.id, new.comment, new.tag, new.category_raw, new.account);
        END
        """
    )

    # Su contenuto esterno, `DELETE FROM transactions_fts WHERE rowid = old.id` non fa cio'
    # che sembra: serve il comando speciale 'delete'. I valori passati devono essere
    # IDENTICI (stessa trasformazione: qui RAW) a quelli indicizzati dall'INSERT
    # corrispondente, altrimenti l'indice si desincronizza silenziosamente (D6).
    op.execute(
        """
        CREATE TRIGGER trg_transactions_fts_delete AFTER DELETE ON transactions BEGIN
            INSERT INTO transactions_fts(transactions_fts, rowid, comment, tag, category_raw, account)
            VALUES ('delete', old.id, old.comment, old.tag, old.category_raw, old.account);
        END
        """
    )

    # UPDATE e' SEMPRE delete-poi-insert, mai solo insert: la meta' "delete" usa i valori
    # OLD con la stessa trasformazione RAW del trigger DELETE sopra.
    op.execute(
        """
        CREATE TRIGGER trg_transactions_fts_update AFTER UPDATE ON transactions BEGIN
            INSERT INTO transactions_fts(transactions_fts, rowid, comment, tag, category_raw, account)
            VALUES ('delete', old.id, old.comment, old.tag, old.category_raw, old.account);
            INSERT INTO transactions_fts(rowid, comment, tag, category_raw, account)
            VALUES (new.id, new.comment, new.tag, new.category_raw, new.account);
        END
        """
    )

    # Popolamento iniziale: indicizza le righe gia' presenti in transactions al momento
    # in cui questa migration gira (rilevante sul DB reale, che ha dati da F1/F2).
    op.execute("INSERT INTO transactions_fts(transactions_fts) VALUES ('rebuild')")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_transactions_fts_update")
    op.execute("DROP TRIGGER IF EXISTS trg_transactions_fts_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_transactions_fts_insert")
    # DROP TABLE su una virtual table fts5 rimuove anche le shadow table associate
    # (transactions_fts_data/_idx/_docsize/_config) — verificato in T3.
    op.execute("DROP TABLE IF EXISTS transactions_fts")
