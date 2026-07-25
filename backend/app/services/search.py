"""Ricerca full-text su `transactions_fts` (F12, ADR-0029). Nessuna query SQL diretta
sulla virtual table fuori da qui: i router costruiscono il filtro `q` chiamando
`build_match_expression` e verificano `fts_available` prima di usarlo.

Firma con `engine`/`session` sempre espliciti, mai `from app.db import engine`: nei
test punterebbe al DB reale invece che al DB di test (convenzione già seguita da
`backup.py`)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def build_match_expression(q: str | None) -> str | None:
    """Traduce l'input libero dell'utente in un'espressione MATCH per FTS5, al riparo
    da errori di sintassi ed effetti indesiderati.

    Ogni token viene messo tra virgolette doppie (`"` interne raddoppiate, l'escape
    FTS5 per il carattere letterale) e seguito da `*` per il prefix match — così
    parole chiave FTS5 come `AND`/`OR`/`NOT`/`NEAR`, parentesi o virgolette spaiate
    diventano testo letterale da cercare invece di operatori di query. Token multipli
    restano in AND implicito (comportamento di default di FTS5 per token separati da
    spazio). `None` se l'input è `None`, vuoto o contiene solo spazi — segnala
    "nessun filtro testuale", non "cerca la stringa vuota".
    """
    if q is None:
        return None
    tokens = q.split()
    if not tokens:
        return None
    return " ".join(f'"{tok.replace(chr(34), chr(34) * 2)}"*' for tok in tokens)


def fts_available(session: Session) -> bool:
    """True se `transactions_fts` esiste ed è interrogabile. Usata dal router per
    rispondere **503** (mai un 500 opaco) quando il filtro `q` è richiesto ma l'indice
    non c'è — es. DB migrato solo fino a `0004`, o test su `Base.metadata.create_all()`
    che non conosce le virtual table."""
    try:
        session.execute(text("SELECT 1 FROM transactions_fts LIMIT 0"))
        return True
    except OperationalError:
        return False


def rebuild_fts_index(engine: Engine) -> None:
    """Ricostruisce `transactions_fts` dal contenuto corrente di `transactions` via il
    comando speciale `'rebuild'` (stesso comando usato dalla migration `0005` per il
    popolamento iniziale). Usata dopo `POST /backup/restore` (T15): un restore
    sovrascrive `transactions` senza passare dai trigger, quindi l'indice va
    rigenerato esplicitamente."""
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO transactions_fts(transactions_fts) VALUES ('rebuild')"))
