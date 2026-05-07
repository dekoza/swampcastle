"""Human-editable curation files for the audit overlay."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

REQUIRED_WING_NOTE_SECTIONS = ("Pinned context", "Open threads", "Stale assumptions")


class PersonaAlias(BaseModel):
    canonical: str | None = None
    type: Literal["agent_persona"] = "agent_persona"


class NamedAlias(BaseModel):
    canonical: str


class AliasCuration(BaseModel):
    personas: dict[str, PersonaAlias] = Field(default_factory=dict)
    people: dict[str, NamedAlias] = Field(default_factory=dict)
    projects: dict[str, NamedAlias] = Field(default_factory=dict)
    wing_hints: dict[str, str] = Field(default_factory=dict)

    def canonical_persona(self, name: str) -> str:
        for alias, entry in self.personas.items():
            if alias.lower() == name.lower():
                return entry.canonical or alias
        return name


class TunnelRule(BaseModel):
    wing_a: str
    wing_b: str
    room: str
    weight: float = 0.0

    def normalized_wings(self) -> tuple[str, str]:
        return tuple(sorted((self.wing_a, self.wing_b)))

    def key(self) -> tuple[str, tuple[str, str]]:
        return (self.room, self.normalized_wings())


class TunnelCuration(BaseModel):
    allow: list[TunnelRule] = Field(default_factory=list)
    deny: list[TunnelRule] = Field(default_factory=list)
    boost: list[TunnelRule] = Field(default_factory=list)


class WingNote(BaseModel):
    wing: str
    path: str
    sections: dict[str, list[str]]


def _curation_dir(castle_path: str | Path) -> Path:
    return Path(castle_path).expanduser().resolve() / ".swampcastle" / "curation"


def _load_yaml_file(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path.name}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Invalid YAML in {path.name}: top-level object must be a mapping")
    return payload


def load_alias_curation(castle_path: str | Path) -> AliasCuration:
    path = _curation_dir(castle_path) / "aliases.yaml"
    if not path.is_file():
        return AliasCuration()
    payload = _load_yaml_file(path)
    try:
        return AliasCuration.model_validate(payload)
    except Exception as exc:  # pragma: no cover - exercised in CLI/error tests
        raise ValueError(f"Invalid aliases.yaml: {exc}") from exc


def load_tunnel_curation(castle_path: str | Path) -> TunnelCuration:
    path = _curation_dir(castle_path) / "tunnels.yaml"
    if not path.is_file():
        return TunnelCuration()
    payload = _load_yaml_file(path)
    try:
        return TunnelCuration.model_validate(payload)
    except Exception as exc:  # pragma: no cover - exercised in CLI/error tests
        raise ValueError(f"Invalid tunnels.yaml: {exc}") from exc


def _wing_notes_dir(castle_path: str | Path) -> Path:
    return _curation_dir(castle_path) / "wings"


def _parse_wing_note(path: Path) -> WingNote:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc

    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip()
            sections.setdefault(current_section, [])
            continue
        if not line or current_section is None:
            continue
        if line.startswith("- "):
            sections[current_section].append(line[2:].strip())
        else:
            sections[current_section].append(line)

    missing = [section for section in REQUIRED_WING_NOTE_SECTIONS if section not in sections]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{path.name} missing required sections: {joined}")

    return WingNote(wing=path.stem, path=str(path), sections=sections)


def load_wing_note(castle_path: str | Path, wing: str) -> WingNote | None:
    path = _wing_notes_dir(castle_path) / f"{wing}.md"
    if not path.is_file():
        return None
    return _parse_wing_note(path)


def list_wing_notes(castle_path: str | Path) -> list[WingNote]:
    notes_dir = _wing_notes_dir(castle_path)
    if not notes_dir.is_dir():
        return []
    notes = []
    for path in sorted(notes_dir.glob("*.md")):
        notes.append(_parse_wing_note(path))
    return notes


def resolve_wing_hint(castle_path: str | Path, source_path: str | Path) -> str | None:
    aliases = load_alias_curation(castle_path)
    if not aliases.wing_hints:
        return None

    haystack = str(Path(source_path)).lower()
    matches = [
        (hint, wing) for hint, wing in aliases.wing_hints.items() if hint.lower() in haystack
    ]
    if not matches:
        return None

    matches.sort(key=lambda item: len(item[0]), reverse=True)
    return matches[0][1]
