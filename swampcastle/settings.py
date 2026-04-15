"""SwampCastle configuration via Pydantic BaseSettings.

Priority: env vars (SWAMPCASTLE_*) > JSON config file > defaults.
"""

import json
import os
from pathlib import Path
from typing import Any, Literal, Optional, Tuple, Type

from pydantic import Field, computed_field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class _JsonFileSource(PydanticBaseSettingsSource):
    """Load settings from a JSON file passed as _json_file init arg."""

    def __init__(self, settings_cls: Type[BaseSettings], json_path: str | None):
        super().__init__(settings_cls)
        self._data: dict[str, Any] = {}
        if json_path:
            path = Path(json_path)
            if path.is_file():
                try:
                    self._data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass

    def get_field_value(self, field, field_name):
        val = self._data.get(field_name)
        return val, field_name, val is not None

    def __call__(self) -> dict[str, Any]:
        return {k: v for k, v in self._data.items() if k in self.settings_cls.model_fields}


class CastleSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SWAMPCASTLE_",
        env_file=None,
    )

    castle_path: Path = Field(default_factory=lambda: Path.home() / ".swampcastle" / "castle")
    collection_name: str = "swampcastle_chests"
    backend: Literal["lance", "postgres", "chroma"] = "lance"
    database_url: Optional[str] = None
    embedder: str = "onnx"
    embedder_model: Optional[str] = None
    embedder_device: Optional[str] = None
    embedder_options: dict[str, Any] = Field(default_factory=dict)
    embed_batch_size: Optional[int] = Field(default=None, ge=1)
    onnx_intra_op_threads: Optional[int] = Field(default=None, ge=1)
    onnx_inter_op_threads: Optional[int] = Field(default=None, ge=1)
    sync_api_key: Optional[str] = Field(
        default=None,
        description=(
            "When set, all sync endpoints require 'Authorization: Bearer <key>'. "
            "Set via SWAMPCASTLE_SYNC_API_KEY env var."
        ),
    )

    _json_file: Optional[str] = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings)

    def __init__(self, _json_file: str | None = None, **kwargs):
        json_data = {}
        if _json_file:
            path = Path(_json_file)
            if path.is_file():
                try:
                    json_data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
        # Only use JSON values for fields not set via env or explicit kwargs
        env_prefix = "SWAMPCASTLE_"
        for k, v in json_data.items():
            if k not in type(self).model_fields:
                continue
            if k in kwargs:
                continue
            env_key = env_prefix + k.upper()
            if env_key in os.environ:
                continue
            kwargs[k] = v
        super().__init__(**kwargs)

    @field_validator("castle_path", mode="before")
    @classmethod
    def _expand_castle_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @computed_field
    @property
    def embedder_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"embedder": self.embedder}
        options = dict(self.embedder_options)

        if self.embedder_device and "device" not in options:
            options["device"] = self.embedder_device
        if self.onnx_intra_op_threads and "intra_op_num_threads" not in options:
            options["intra_op_num_threads"] = self.onnx_intra_op_threads
        if self.onnx_inter_op_threads and "inter_op_num_threads" not in options:
            options["inter_op_num_threads"] = self.onnx_inter_op_threads

        if self.embedder == "ollama":
            if self.embedder_model and "model" not in options:
                options["model"] = self.embedder_model
        elif self.embedder != "onnx" and self.embedder_model:
            config["embedder"] = self.embedder_model

        if options:
            config["embedder_options"] = options
        return config

    @computed_field
    @property
    def kg_path(self) -> Path:
        return self.castle_path.parent / "knowledge_graph.sqlite3"

    @computed_field
    @property
    def wal_path(self) -> Path:
        return self.castle_path.parent / "wal"

    @computed_field
    @property
    def config_dir(self) -> Path:
        return self.castle_path.parent
