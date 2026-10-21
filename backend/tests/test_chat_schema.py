"""Schema F14 (revision 0006): round-trip, CHECK su role, default di truncated."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from conftest import run_alembic_downgrade, run_alembic_upgrade

FTS_TRIGGERS = [
    "trg_transactions_fts_delete",
    "trg_transactions_fts_insert",
    "trg_transactions_fts_update",
]


def _tables(conn) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
    return {r[0] for r in rows}


def _fts_triggers(conn) -> list[str]:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_transactions_fts_%' ORDER BY name")
    ).all()
    return [r[0] for r in rows]


def _check_state(conn, chat_present: bool) -> None:
    tables = _tables(conn)
    assert ("chat_sessions" in tables) is chat_present
    assert ("chat_messages" in tables) is chat_present
    assert _fts_triggers(conn) == FTS_TRIGGERS
    conn.execute(text("INSERT INTO transactions_fts(transactions_fts, rank) VALUES ('integrity-check', 1)"))


def test_round_trip_keeps_fts_triggers(fts_engine):
    with fts_engine.connect() as conn:
        _check_state(conn, chat_present=True)
        run_alembic_downgrade(conn, "0005")
        conn.commit()
        _check_state(conn, chat_present=False)
        run_alembic_upgrade(conn)
        conn.commit()
        _check_state(conn, chat_present=True)


def test_role_check_rejects_invalid_value(fts_engine):
    with fts_engine.connect() as conn:
        conn.execute(text("INSERT INTO chat_sessions (title, created_at, updated_at) VALUES ('t', '2026-01-01', '2026-01-01')"))
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO chat_messages (session_id, role, content, created_at) "
                    "VALUES (1, 'system', 'x', '2026-01-01')"
                )
            )


def test_truncated_defaults_to_zero(fts_engine):
    with fts_engine.connect() as conn:
        conn.execute(text("INSERT INTO chat_sessions (title, created_at, updated_at) VALUES ('t', '2026-01-01', '2026-01-01')"))
        conn.execute(
            text(
                "INSERT INTO chat_messages (session_id, role, content, created_at) "
                "VALUES (1, 'user', 'x', '2026-01-01')"
            )
        )
        assert conn.execute(text("SELECT truncated FROM chat_messages")).scalar() == 0
