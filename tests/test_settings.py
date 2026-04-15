"""Tests for swampcastle.settings — CastleSettings (Pydantic BaseSettings)."""

import json
from pathlib import Path

import pytest

from swampcastle.settings import CastleSettings
from swampcastle.wal import WalWriter


@pytest.fixture(autouse=True)
def clear_swampcastle_env(monkeypatch):
    for key in [
        "SWAMPCASTLE_CASTLE_PATH",
        "SWAMPCASTLE_BACKEND",
        "SWAMPCASTLE_DATABASE_URL",
        "SWAMPCASTLE_EMBEDDER",
        "SWAMPCASTLE_EMBEDDER_DEVICE",
    ]:
        monkeypatch.delenv(key, raising=False)


class TestDefaults:
    def test_default_castle_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        s = CastleSettings(_env_file=None)
        assert s.castle_path == tmp_path / ".swampcastle" / "castle"
        assert s.castle_path.is_absolute()

    def test_default_collection_name(self):
        s = CastleSettings(_env_file=None)
        assert s.collection_name == "swampcastle_chests"

    def test_default_backend(self):
        s = CastleSettings(_env_file=None)
        assert s.backend == "lance"

    def test_default_embedder(self):
        s = CastleSettings(_env_file=None)
        assert s.embedder == "onnx"

    def test_default_embedder_config(self):
        s = CastleSettings(_env_file=None)
        assert s.embedder_config == {"embedder": "onnx"}


class TestComputedPaths:
    def test_kg_path_derived_from_castle_path(self):
        s = CastleSettings(castle_path="/tmp/test/castle", _env_file=None)
        assert s.kg_path == Path("/tmp/test/knowledge_graph.sqlite3")

    def test_wal_path_derived_from_castle_path(self):
        s = CastleSettings(castle_path="/tmp/test/castle", _env_file=None)
        assert s.wal_path == Path("/tmp/test/wal")

    def test_config_dir_derived_from_castle_path(self):
        s = CastleSettings(castle_path="/tmp/test/castle", _env_file=None)
        assert s.config_dir == Path("/tmp/test")


class TestEnvOverride:
    def test_env_castle_path(self, monkeypatch):
        monkeypatch.setenv("SWAMPCASTLE_CASTLE_PATH", "/env/path")
        s = CastleSettings(_env_file=None)
        assert str(s.castle_path) == "/env/path"

    def test_env_castle_path_expands_user_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("SWAMPCASTLE_CASTLE_PATH", "~/.swampcastle/castle")
        s = CastleSettings(_env_file=None)
        assert s.castle_path == tmp_path / ".swampcastle" / "castle"

    def test_env_backend(self, monkeypatch):
        monkeypatch.setenv("SWAMPCASTLE_BACKEND", "postgres")
        s = CastleSettings(_env_file=None)
        assert s.backend == "postgres"

    def test_env_database_url(self, monkeypatch):
        monkeypatch.setenv("SWAMPCASTLE_DATABASE_URL", "postgresql://localhost/test")
        s = CastleSettings(_env_file=None)
        assert s.database_url == "postgresql://localhost/test"


class TestEmbedderConfig:
    def test_embedder_config_uses_explicit_device(self):
        s = CastleSettings(embedder="bge-small", embedder_device="cpu", _env_file=None)
        assert s.embedder_config == {
            "embedder": "bge-small",
            "embedder_options": {"device": "cpu"},
        }

    def test_embedder_config_merges_ollama_model_and_options(self):
        s = CastleSettings(
            embedder="ollama",
            embedder_model="nomic-embed-text",
            embedder_options={"base_url": "http://server:11434"},
            _env_file=None,
        )
        assert s.embedder_config == {
            "embedder": "ollama",
            "embedder_options": {
                "model": "nomic-embed-text",
                "base_url": "http://server:11434",
            },
        }


class TestJsonFile:
    def test_load_from_json(self, tmp_path):
        config = {"castle_path": "/from/json", "backend": "chroma"}
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps(config))
        s = CastleSettings(_env_file=None, _json_file=str(json_path))
        assert str(s.castle_path) == "/from/json"
        assert s.backend == "chroma"

    def test_json_castle_path_expands_user_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps({"castle_path": "~/.swampcastle/castle"}))
        s = CastleSettings(_env_file=None, _json_file=str(json_path))
        assert s.castle_path == tmp_path / ".swampcastle" / "castle"

    def test_env_overrides_json(self, tmp_path, monkeypatch):
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps({"castle_path": "/from/json"}))
        monkeypatch.setenv("SWAMPCASTLE_CASTLE_PATH", "/from/env")
        s = CastleSettings(_env_file=None, _json_file=str(json_path))
        assert str(s.castle_path) == "/from/env"

    def test_invalid_json_is_ignored(self, tmp_path):
        json_path = tmp_path / "broken.json"
        json_path.write_text("{not valid json")
        s = CastleSettings(_env_file=None, _json_file=str(json_path))
        assert str(s.castle_path).endswith(".swampcastle/castle")

    def test_unknown_json_keys_are_ignored(self, tmp_path):
        json_path = tmp_path / "config.json"
        json_path.write_text(json.dumps({"castle_path": "/from/json", "bogus": "x"}))
        s = CastleSettings(_env_file=None, _json_file=str(json_path))
        assert str(s.castle_path) == "/from/json"
        assert not hasattr(s, "bogus")

    def test_missing_json_file_is_ignored(self, tmp_path):
        s = CastleSettings(_env_file=None, _json_file=str(tmp_path / "missing.json"))
        assert str(s.castle_path).endswith(".swampcastle/castle")


class TestValidation:
    def test_backend_must_be_valid(self):
        with pytest.raises(Exception):
            CastleSettings(backend="nosql_yolo", _env_file=None)

    def test_castle_path_accepts_string(self):
        s = CastleSettings(castle_path="/tmp/x", _env_file=None)
        assert isinstance(s.castle_path, Path)

    def test_castle_path_expands_user_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        s = CastleSettings(castle_path="~/.swampcastle/castle", _env_file=None)
        assert s.castle_path == tmp_path / ".swampcastle" / "castle"


class TestPathSideEffects:
    def test_default_wal_path_does_not_create_literal_tilde_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        config_dir = tmp_path / ".swampcastle"
        config_dir.mkdir()
        monkeypatch.chdir(config_dir)

        settings = CastleSettings(_env_file=None)
        WalWriter(settings.wal_path)

        assert not (config_dir / "~").exists()
        assert settings.wal_path == tmp_path / ".swampcastle" / "wal"
        assert settings.wal_path.exists()
