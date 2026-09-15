from ruinform_intelligence import run_store


def test_sqlite_is_used_without_database_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RUINFORM_DATABASE_URL", raising=False)

    store = run_store.SqliteRunStore(str(tmp_path / "local.db"))

    assert isinstance(store, run_store.SqliteRunStore)
    assert store.backend_name == "sqlite"


def test_existing_sqlite_constructor_routes_to_postgres_when_database_url_exists(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/ruinform")

    class FakePostgresStore:
        backend_name = "postgres"

        def __init__(self):
            self.created = True

    monkeypatch.setattr(run_store, "PostgresRunStore", FakePostgresStore)

    store = run_store.SqliteRunStore()

    assert isinstance(store, FakePostgresStore)
    assert store.backend_name == "postgres"


def test_factory_prefers_postgres_when_database_url_exists(monkeypatch):
    monkeypatch.setenv("RUINFORM_DATABASE_URL", "postgresql://example.invalid/ruinform")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    class FakePostgresStore:
        backend_name = "postgres"

        def __init__(self):
            self.created = True

    monkeypatch.setattr(run_store, "PostgresRunStore", FakePostgresStore)

    store = run_store.create_run_store()

    assert isinstance(store, FakePostgresStore)
