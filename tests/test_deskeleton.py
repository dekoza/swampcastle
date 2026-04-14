from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from swampcastle.cli import commands
from swampcastle.mining.miner import mine
from swampcastle.settings import CastleSettings
from swampcastle.storage import factory_from_settings


def _write_project_config(project_root: Path, wing: str = "alpha") -> None:
    (project_root / ".swampcastle.yaml").write_text(
        yaml.dump(
            {
                "wing": wing,
                "rooms": [{"name": "general", "description": "General"}],
            }
        ),
        encoding="utf-8",
    )


def _write_large_python_file(path: Path) -> None:
    func_blocks = []
    for i in range(300):
        body = "\n".join([f"    line_{j} = {j} * 2  # padding" for j in range(10)])
        func_blocks.append(f"def func_{i}(x, y=None):\n{body}\n    return x")
    path.write_text("\n\n".join(func_blocks), encoding="utf-8")


def _rows_for_file(palace_path: Path, source_file: Path, wing: str) -> dict:
    settings = CastleSettings(castle_path=palace_path, _env_file=None)
    factory = factory_from_settings(settings)
    try:
        collection = factory.open_collection("swampcastle_chests")
        return collection.get(
            where={"source_file": str(source_file), "wing": wing},
            include=["documents", "metadatas"],
        )
    finally:
        factory.close()


def _deskeleton_args(palace_path: Path, *, wing: str | None = None, dry_run: bool = False):
    return SimpleNamespace(
        palace=str(palace_path),
        backend=None,
        wing=wing,
        room=None,
        dry_run=dry_run,
    )


def test_cmd_deskeleton_finds_skeleton_drawers_on_lance(tmp_path, monkeypatch, capsys):
    runtime_config = tmp_path / "runtime-config.json"
    runtime_config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("swampcastle.cli.commands.ensure_runtime_config", lambda: runtime_config)

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project_config(project_root, wing="alpha")
    source = project_root / "large.py"
    _write_large_python_file(source)

    palace_path = tmp_path / "palace"
    mine(str(project_root), str(palace_path))

    before = _rows_for_file(palace_path, source, "alpha")
    assert any(meta.get("is_skeleton") for meta in before["metadatas"])

    commands.cmd_deskeleton(_deskeleton_args(palace_path, dry_run=True))

    out = capsys.readouterr().out
    assert "No skeleton drawers found." not in out
    assert str(source) in out


def test_cmd_deskeleton_replaces_skeleton_with_full_file_on_lance(tmp_path, monkeypatch):
    runtime_config = tmp_path / "runtime-config.json"
    runtime_config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("swampcastle.cli.commands.ensure_runtime_config", lambda: runtime_config)

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project_config(project_root, wing="alpha")
    source = project_root / "large.py"
    _write_large_python_file(source)

    palace_path = tmp_path / "palace"
    mine(str(project_root), str(palace_path))

    before = _rows_for_file(palace_path, source, "alpha")
    before_text = "\n".join(before["documents"])
    assert any(meta.get("is_skeleton") for meta in before["metadatas"])
    assert "line_0 = 0 * 2" not in before_text

    commands.cmd_deskeleton(_deskeleton_args(palace_path))

    after = _rows_for_file(palace_path, source, "alpha")
    after_text = "\n".join(after["documents"])
    assert after["ids"]
    assert all(not meta.get("is_skeleton") for meta in after["metadatas"])
    assert "line_0 = 0 * 2" in after_text


def test_cmd_deskeleton_preserves_target_wing(tmp_path, monkeypatch):
    runtime_config = tmp_path / "runtime-config.json"
    runtime_config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("swampcastle.cli.commands.ensure_runtime_config", lambda: runtime_config)

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_project_config(project_root, wing="alpha")
    source = project_root / "large.py"
    _write_large_python_file(source)

    palace_path = tmp_path / "palace"
    mine(str(project_root), str(palace_path), wing="alpha")
    mine(str(project_root), str(palace_path), wing="beta")

    alpha_before = _rows_for_file(palace_path, source, "alpha")
    beta_before = _rows_for_file(palace_path, source, "beta")
    assert any(meta.get("is_skeleton") for meta in alpha_before["metadatas"])
    assert any(meta.get("is_skeleton") for meta in beta_before["metadatas"])

    commands.cmd_deskeleton(_deskeleton_args(palace_path, wing="beta"))

    alpha_after = _rows_for_file(palace_path, source, "alpha")
    beta_after = _rows_for_file(palace_path, source, "beta")
    assert any(meta.get("is_skeleton") for meta in alpha_after["metadatas"])
    assert all(not meta.get("is_skeleton") for meta in beta_after["metadatas"])
