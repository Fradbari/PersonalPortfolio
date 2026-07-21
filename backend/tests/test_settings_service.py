from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings as app_settings
from app.db import Base
from app.models import Settings
from app.services import settings as settings_service
from app.services.settings import BLACKLIST, WHITELIST, get_effective, set_values


def _build_test_session_maker():
    # StaticPool: connessione unica in-memory condivisa (stesso pattern di
    # test_insights_service.py / test_backup_core.py).
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


# --- WHITELIST / BLACKLIST shape ---------------------------------------------


def test_whitelist_has_exactly_the_six_expected_keys():
    assert set(WHITELIST.keys()) == {
        "theme",
        "metabase_url",
        "ai_history_max_turns",
        "import_min_year",
        "backup_retention",
        "backup_on_startup",
    }


def test_blacklist_contains_the_three_secrets():
    assert BLACKLIST == frozenset({"ai_api_key", "google_sa_key_path", "gdrive_backup_folder_id"})


# --- get_effective: precedenza default (letterale) --> db, per le 3 chiavi senza env ---


def test_theme_default_is_system_when_nothing_set():
    Session = _build_test_session_maker()
    with Session() as session:
        value, source = get_effective("theme", session=session)
    assert (value, source) == ("system", "default")


def test_theme_db_overrides_default():
    Session = _build_test_session_maker()
    with Session() as session:
        session.add(Settings(key="theme", value="dark"))
        session.commit()
        value, source = get_effective("theme", session=session)
    assert (value, source) == ("dark", "db")


def test_metabase_url_default_when_nothing_set():
    Session = _build_test_session_maker()
    with Session() as session:
        value, source = get_effective("metabase_url", session=session)
    assert (value, source) == ("http://localhost:3000", "default")


def test_metabase_url_db_overrides_default():
    Session = _build_test_session_maker()
    with Session() as session:
        session.add(Settings(key="metabase_url", value="http://raspberry.local:3000"))
        session.commit()
        value, source = get_effective("metabase_url", session=session)
    assert (value, source) == ("http://raspberry.local:3000", "db")


def test_ai_history_max_turns_default_when_nothing_set():
    Session = _build_test_session_maker()
    with Session() as session:
        value, source = get_effective("ai_history_max_turns", session=session)
    assert (value, source) == (6, "default")


def test_ai_history_max_turns_db_overrides_default_and_coerces_to_int():
    Session = _build_test_session_maker()
    with Session() as session:
        session.add(Settings(key="ai_history_max_turns", value="12"))
        session.commit()
        value, source = get_effective("ai_history_max_turns", session=session)
    assert (value, source) == (12, "db")
    assert isinstance(value, int)


# --- get_effective: precedenza env --> db, per le 3 chiavi con env_attr ---


def test_import_min_year_falls_back_to_env_when_nothing_in_db():
    Session = _build_test_session_maker()
    with Session() as session:
        value, source = get_effective("import_min_year", session=session)
    assert (value, source) == (app_settings.import_min_year, "env")


def test_import_min_year_db_overrides_env_and_coerces_to_int():
    Session = _build_test_session_maker()
    with Session() as session:
        session.add(Settings(key="import_min_year", value="2020"))
        session.commit()
        value, source = get_effective("import_min_year", session=session)
    assert (value, source) == (2020, "db")
    assert isinstance(value, int)


def test_backup_retention_falls_back_to_env_when_nothing_in_db():
    Session = _build_test_session_maker()
    with Session() as session:
        value, source = get_effective("backup_retention", session=session)
    assert (value, source) == (app_settings.backup_retention, "env")


def test_backup_retention_db_overrides_env_and_coerces_to_int():
    Session = _build_test_session_maker()
    with Session() as session:
        session.add(Settings(key="backup_retention", value="5"))
        session.commit()
        value, source = get_effective("backup_retention", session=session)
    assert (value, source) == (5, "db")
    assert isinstance(value, int)


def test_backup_on_startup_falls_back_to_env_when_nothing_in_db():
    Session = _build_test_session_maker()
    with Session() as session:
        value, source = get_effective("backup_on_startup", session=session)
    assert (value, source) == (app_settings.backup_on_startup, "env")
    assert isinstance(value, bool)


def test_backup_on_startup_db_overrides_env_and_coerces_string_to_bool():
    Session = _build_test_session_maker()
    with Session() as session:
        session.add(Settings(key="backup_on_startup", value="true"))
        session.commit()
        value, source = get_effective("backup_on_startup", session=session)
    assert (value, source) == (True, "db")
    assert isinstance(value, bool)

    with Session() as session:
        row = session.get(Settings, "backup_on_startup")
        row.value = "false"
        session.commit()
        value, source = get_effective("backup_on_startup", session=session)
    assert (value, source) == (False, "db")
    assert isinstance(value, bool)


# --- get_effective: chiave non whitelist ---


def test_get_effective_rejects_unknown_key():
    Session = _build_test_session_maker()
    with Session() as session:
        try:
            get_effective("ai_api_key", session=session)
            assert False, "doveva sollevare"
        except ValueError:
            pass


# --- set_values: scrittura, coercizione, transazione unica -------------------


def test_set_values_writes_new_row_with_type_coercion_to_string():
    Session = _build_test_session_maker()
    with Session() as session:
        set_values(session, {"theme": "dark", "ai_history_max_turns": 10})

    with Session() as session:
        theme_row = session.get(Settings, "theme")
        turns_row = session.get(Settings, "ai_history_max_turns")
        assert theme_row.value == "dark"
        assert turns_row.value == "10"  # stored as TEXT


def test_set_values_updates_existing_row_and_updated_at():
    Session = _build_test_session_maker()
    with Session() as session:
        session.add(Settings(key="theme", value="light"))
        session.commit()

    with Session() as session:
        set_values(session, {"theme": "dark"})

    with Session() as session:
        row = session.get(Settings, "theme")
        assert row.value == "dark"
        assert row.updated_at is not None


def test_set_values_bool_coercion_stores_canonical_string():
    Session = _build_test_session_maker()
    with Session() as session:
        set_values(session, {"backup_on_startup": True})

    with Session() as session:
        row = session.get(Settings, "backup_on_startup")
        assert row.value == "true"


def test_set_values_rejects_non_whitelist_key_and_writes_nothing():
    Session = _build_test_session_maker()
    with Session() as session:
        try:
            set_values(session, {"theme": "dark", "ai_api_key": "leak"})
            assert False, "doveva sollevare"
        except ValueError:
            pass

    with Session() as session:
        assert session.get(Settings, "theme") is None
        assert session.get(Settings, "ai_api_key") is None


def test_set_values_rejects_unknown_key_and_writes_nothing():
    Session = _build_test_session_maker()
    with Session() as session:
        try:
            set_values(session, {"theme": "dark", "not_a_real_setting": "x"})
            assert False, "doveva sollevare"
        except ValueError:
            pass

    with Session() as session:
        assert session.get(Settings, "theme") is None


# --- get_effective: ramo session=None -----------------------------------------


def test_get_effective_session_none_opens_and_closes_its_own_session(monkeypatch):
    Session = _build_test_session_maker()
    closed_flags = []

    def tracking_factory():
        session = Session()
        original_close = session.close

        def close_and_record():
            closed_flags.append(True)
            original_close()

        session.close = close_and_record
        return session

    monkeypatch.setattr(settings_service, "SessionLocal", tracking_factory)

    value, source = get_effective("theme")

    assert (value, source) == ("system", "default")
    assert closed_flags == [True]


def test_get_effective_session_none_closes_session_even_on_exception(monkeypatch):
    Session = _build_test_session_maker()
    closed_flags = []

    def tracking_factory():
        session = Session()
        original_close = session.close

        def close_and_record():
            closed_flags.append(True)
            original_close()

        session.close = close_and_record
        return session

    monkeypatch.setattr(settings_service, "SessionLocal", tracking_factory)
    # Rompe la risoluzione env di una chiave valida per forzare un'eccezione
    # *dopo* l'apertura della sessione interna, per verificare che `finally` la chiuda comunque.
    monkeypatch.setitem(
        settings_service.WHITELIST["import_min_year"], "env_attr", "does_not_exist_on_app_settings"
    )

    try:
        get_effective("import_min_year")
        assert False, "doveva sollevare"
    except AttributeError:
        pass

    assert closed_flags == [True]
