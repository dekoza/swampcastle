"""Interactive wizard for global SwampCastle runtime configuration.

This command owns:
- backend selection (lance / postgres)
- castle path
- postgres connection settings
- personal identity setup (people, projects, usage mode)

It does NOT own:
- project-local mining config (.swampcastle.yaml)
- migration
- room detection
"""

from __future__ import annotations

from pathlib import Path

from swampcastle.runtime_config import load_runtime_config, save_runtime_config


def _prompt(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    value = input(f"  {prompt}{suffix}: ").strip()
    if value:
        return value
    return default or ""


def _yn(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    val = input(f"  {prompt} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


# ── Backend configuration ────────────────────────────────────────────────────


def _configure_backend(config: dict) -> dict:
    print("\n  --- Storage backend ---\n")

    backend = _prompt("Backend (lance/postgres)", str(config.get("backend", "lance"))).lower()
    while backend not in {"lance", "postgres"}:
        print("  Please enter 'lance' or 'postgres'.")
        backend = _prompt("Backend (lance/postgres)", str(config.get("backend", "lance"))).lower()

    castle_path = _prompt("Castle path", str(config.get("castle_path", "")))

    updated = {
        "castle_path": castle_path,
        "backend": backend,
        "collection_name": config.get("collection_name", "swampcastle_chests"),
        "embedder": config.get("embedder", "onnx"),
    }

    if backend == "postgres":
        database_url = _prompt("Database URL", str(config.get("database_url", "")))
        while not database_url:
            print("  PostgreSQL requires a database URL.")
            database_url = _prompt("Database URL", str(config.get("database_url", "")))
        updated["database_url"] = database_url

    return updated


# ── Personal identity setup ──────────────────────────────────────────────────


def _ask_mode() -> str:
    print("\n  --- Usage mode ---\n")
    print("  How are you using SwampCastle?\n")
    print("    [1]  Work      — projects, clients, colleagues, decisions")
    print("    [2]  Personal  — diary, family, health, relationships")
    print("    [3]  Both      — personal and professional mixed")
    print()

    while True:
        choice = input("  Your choice [1/2/3]: ").strip()
        if choice == "1":
            return "work"
        if choice == "2":
            return "personal"
        if choice == "3":
            return "combo"
        print("  Please enter 1, 2, or 3.")


def _ask_people(mode: str) -> list[dict]:
    people = []

    if mode in ("personal", "combo"):
        print("\n  --- People (personal) ---\n")
        print("  Who are the important people in your life?")
        print("  Format: name, relationship (e.g. 'Riley, daughter')")
        print("  Enter blank line when done.\n")
        while True:
            entry = input("  Person: ").strip()
            if not entry:
                break
            parts = [p.strip() for p in entry.split(",", 1)]
            name = parts[0]
            relationship = parts[1] if len(parts) > 1 else ""
            if name:
                people.append({"name": name, "relationship": relationship, "context": "personal"})

    if mode in ("work", "combo"):
        print("\n  --- People (work) ---\n")
        print("  Colleagues, clients, or collaborators you mention in notes?")
        print("  Format: name, role (e.g. 'Sarah, team lead')")
        print("  Enter blank line when done.\n")
        while True:
            entry = input("  Person: ").strip()
            if not entry:
                break
            parts = [p.strip() for p in entry.split(",", 1)]
            name = parts[0]
            role = parts[1] if len(parts) > 1 else ""
            if name:
                people.append({"name": name, "relationship": role, "context": "work"})

    return people


def _ask_projects() -> list[str]:
    print("\n  --- Projects ---\n")
    print("  What are your main projects? These help SwampCastle tell")
    print("  project names from ordinary words.")
    print("  Enter blank line when done.\n")
    projects = []
    while True:
        proj = input("  Project: ").strip()
        if not proj:
            break
        projects.append(proj)
    return projects


def _save_identity(
    mode: str, people: list[dict], projects: list[str], config_dir: Path | None = None
) -> None:
    from swampcastle.runtime_config import runtime_config_dir

    from swampcastle.entity_registry import EntityRegistry

    resolved_dir = config_dir or runtime_config_dir()
    registry = EntityRegistry.load(resolved_dir)
    registry.seed(mode=mode, people=people, projects=projects, aliases={})

    resolved_dir.mkdir(parents=True, exist_ok=True)

    entity_codes = {}
    for person in people:
        name = person["name"]
        code = name[:3].upper()
        while code in entity_codes.values():
            code = name[:4].upper()
        entity_codes[name] = code

    lines = ["# AAAK Entity Registry", ""]
    if people:
        lines.append("## People")
        for person in people:
            name = person["name"]
            code = entity_codes[name]
            rel = person.get("relationship", "")
            lines.append(f"  {code}={name} ({rel})" if rel else f"  {code}={name}")
    if projects:
        lines.extend(["", "## Projects"])
        for proj in projects:
            lines.append(f"  {proj[:4].upper()}={proj}")

    (resolved_dir / "aaak_entities.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n  Identity saved: {registry._path}")
    print(f"  AAAK entities:  {resolved_dir / 'aaak_entities.md'}")


# ── Main wizard flow ─────────────────────────────────────────────────────────


def run_wizard() -> None:
    config = load_runtime_config()

    print("  SwampCastle Wizard")
    print("  Configure global runtime and personal identity settings.")

    # Part 1: backend
    updated = _configure_backend(config)
    config_path = save_runtime_config(updated)
    print(f"\n  Saved runtime config: {config_path}")

    # Part 2: personal identity (optional)
    if _yn("\n  Set up personal identity? (people, projects, usage mode)", default=True):
        mode = _ask_mode()
        people = _ask_people(mode)
        projects = _ask_projects() if mode != "personal" else []
        _save_identity(mode, people, projects)

    print("\n  Wizard complete.")
