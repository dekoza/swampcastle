"""Tests for storage factory routing."""

from types import SimpleNamespace

import pytest

from swampcastle.settings import CastleSettings
from swampcastle.storage import StorageFactory, factory_from_settings
from swampcastle.storage.lance import LocalStorageFactory


class TestFactoryRouter:
    def test_local_storage_factory_is_storage_factory(self, tmp_path):
        factory = LocalStorageFactory(tmp_path / "castle")
        assert isinstance(factory, StorageFactory)

    def test_lance_backend_returns_local_storage_factory(self, tmp_path):
        settings = CastleSettings(castle_path=tmp_path / "castle", backend="lance", _env_file=None)
        factory = factory_from_settings(settings)
        assert isinstance(factory, LocalStorageFactory)

    def test_chroma_backend_raises_not_implemented(self, tmp_path):
        settings = CastleSettings(castle_path=tmp_path / "castle", backend="chroma", _env_file=None)
        with pytest.raises(NotImplementedError, match="removed in v4"):
            factory_from_settings(settings)

    def test_unknown_backend_raises_value_error(self, tmp_path):
        settings = SimpleNamespace(
            castle_path=tmp_path / "castle",
            backend="nosql_yolo",
            database_url=None,
        )
        with pytest.raises(ValueError, match="Unknown backend"):
            factory_from_settings(settings)

    def test_postgres_backend_without_database_url_raises_value_error(self, tmp_path):
        settings = CastleSettings(
            castle_path=tmp_path / "castle", backend="postgres", _env_file=None
        )
        with pytest.raises(ValueError, match="SWAMPCASTLE_DATABASE_URL"):
            factory_from_settings(settings)

    def test_postgres_backend_missing_dependency_raises_helpful_import_error(
        self, tmp_path, monkeypatch
    ):
        settings = CastleSettings(
            castle_path=tmp_path / "castle",
            backend="postgres",
            database_url="postgresql://localhost/swampcastle",
            _env_file=None,
        )

        def fake_import_module(name):
            raise ImportError("No module named 'psycopg_pool'")

        monkeypatch.setattr("swampcastle.storage.import_module", fake_import_module)

        with pytest.raises(ImportError, match=r"swampcastle\[postgres\]"):
            factory_from_settings(settings)

    def test_postgres_backend_returns_postgres_factory(self, tmp_path, monkeypatch):
        from swampcastle.storage.postgres import PostgresStorageFactory

        settings = CastleSettings(
            castle_path=tmp_path / "castle",
            backend="postgres",
            database_url="postgresql://localhost/swampcastle",
            _env_file=None,
        )

        class DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def execute(self, sql, params=None):
                return None

        class DummyConnection:
            def cursor(self):
                return DummyCursor()

            def commit(self):
                return None

        class DummyPool:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def open(self):
                return None

            def wait(self):
                return None

            def connection(self):
                class _Context:
                    def __enter__(self_inner):
                        return DummyConnection()

                    def __exit__(self_inner, *exc):
                        return None

                return _Context()

            def close(self):
                return None

        class DummyPsycopg:
            @staticmethod
            def connect(dsn):
                class _Context:
                    def __enter__(self_inner):
                        return DummyConnection()

                    def __exit__(self_inner, *exc):
                        return None

                return _Context()

        monkeypatch.setattr("swampcastle.storage.postgres.ConnectionPool", DummyPool)
        monkeypatch.setattr("swampcastle.storage.postgres.register_vector", lambda conn: None)
        monkeypatch.setattr("swampcastle.storage.postgres.Vector", lambda value: value)
        monkeypatch.setattr("swampcastle.storage.postgres.psycopg", DummyPsycopg)

        factory = factory_from_settings(settings)
        assert isinstance(factory, PostgresStorageFactory)
        assert factory._database_url == "postgresql://localhost/swampcastle"
