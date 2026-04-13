#!/usr/bin/env python3
"""
room_detector_local.py — Local setup, no API required.

Two ways to define rooms without calling any AI:
  1. Auto-detect from folder structure (zero config)
  2. Define manually in swampcastle.yaml

No internet. No API key. Your files stay on your machine.
"""

from collections import defaultdict
from pathlib import Path
import os
import sys

import yaml

from swampcastle.project_config import project_config_path

# Common room patterns — detected from folder names and filenames
# Format: {folder_keyword: room_name}
FOLDER_ROOM_MAP = {
    "frontend": "frontend",
    "front-end": "frontend",
    "front_end": "frontend",
    "client": "frontend",
    "ui": "frontend",
    "views": "frontend",
    "components": "frontend",
    "pages": "frontend",
    "backend": "backend",
    "back-end": "backend",
    "back_end": "backend",
    "server": "backend",
    "api": "backend",
    "routes": "backend",
    "services": "backend",
    "controllers": "backend",
    "models": "backend",
    "database": "backend",
    "db": "backend",
    "docs": "documentation",
    "doc": "documentation",
    "documentation": "documentation",
    "wiki": "documentation",
    "readme": "documentation",
    "notes": "documentation",
    "design": "design",
    "designs": "design",
    "mockups": "design",
    "wireframes": "design",
    "assets": "design",
    "storyboard": "design",
    "costs": "costs",
    "cost": "costs",
    "budget": "costs",
    "finance": "costs",
    "financial": "costs",
    "pricing": "costs",
    "invoices": "costs",
    "accounting": "costs",
    "meetings": "meetings",
    "meeting": "meetings",
    "calls": "meetings",
    "meeting_notes": "meetings",
    "standup": "meetings",
    "minutes": "meetings",
    "team": "team",
    "staff": "team",
    "hr": "team",
    "hiring": "team",
    "employees": "team",
    "people": "team",
    "research": "research",
    "references": "research",
    "reading": "research",
    "papers": "research",
    "planning": "planning",
    "roadmap": "planning",
    "strategy": "planning",
    "specs": "planning",
    "requirements": "planning",
    "tests": "testing",
    "test": "testing",
    "testing": "testing",
    "qa": "testing",
    "scripts": "scripts",
    "tools": "scripts",
    "utils": "scripts",
    "config": "configuration",
    "configs": "configuration",
    "settings": "configuration",
    "infrastructure": "configuration",
    "infra": "configuration",
    "deploy": "configuration",
}


def detect_rooms_from_folders(project_dir: str) -> list:
    """
    Walk the project folder structure.
    Find top-level subdirectories that match known room patterns.
    Returns list of room dicts.
    """
    project_path = Path(project_dir).expanduser().resolve()
    found_rooms = {}

    SKIP_DIRS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        "coverage",
    }

    # Check top-level directories first (most reliable signal)
    for item in project_path.iterdir():
        if item.is_dir() and item.name not in SKIP_DIRS:
            name_lower = item.name.lower().replace("-", "_")
            if name_lower in FOLDER_ROOM_MAP:
                room_name = FOLDER_ROOM_MAP[name_lower]
                if room_name not in found_rooms:
                    found_rooms[room_name] = item.name
            # Also check if folder name IS a good room name directly
            elif len(item.name) > 2 and item.name[0].isalpha():
                clean = item.name.lower().replace("-", "_").replace(" ", "_")
                if clean not in found_rooms:
                    found_rooms[clean] = item.name

    # Walk one level deeper for nested patterns
    for item in project_path.iterdir():
        if item.is_dir() and item.name not in SKIP_DIRS:
            for subitem in item.iterdir():
                if subitem.is_dir() and subitem.name not in SKIP_DIRS:
                    name_lower = subitem.name.lower().replace("-", "_")
                    if name_lower in FOLDER_ROOM_MAP:
                        room_name = FOLDER_ROOM_MAP[name_lower]
                        if room_name not in found_rooms:
                            found_rooms[room_name] = subitem.name

    # Build room list
    rooms = []
    for room_name, original in found_rooms.items():
        rooms.append(
            {
                "name": room_name,
                "description": f"Files from {original}/",
                "keywords": [room_name, original.lower()],
            }
        )

    # Always add "general" as fallback
    if not any(r["name"] == "general" for r in rooms):
        rooms.append(
            {
                "name": "general",
                "description": "Files that don't fit other rooms",
                "keywords": [],
            }
        )

    return rooms


def detect_rooms_from_files(project_dir: str) -> list:
    """
    Fallback: if folder structure gives no signal,
    detect rooms from recurring filename patterns.
    """
    project_path = Path(project_dir).expanduser().resolve()
    keyword_counts = defaultdict(int)

    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in filenames:
            name_lower = filename.lower().replace("-", "_").replace(" ", "_")
            for keyword, room in FOLDER_ROOM_MAP.items():
                if keyword in name_lower:
                    keyword_counts[room] += 1

    # Return rooms that appear more than twice
    rooms = []
    for room, count in sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True):
        if count >= 2:
            rooms.append(
                {
                    "name": room,
                    "description": f"Files related to {room}",
                    "keywords": [room],
                }
            )
        if len(rooms) >= 6:
            break

    if not rooms:
        rooms = [{"name": "general", "description": "All project files", "keywords": []}]

    return rooms


def print_proposed_structure(project_name: str, rooms: list, total_files: int):
    print(f"\n{'=' * 55}")
    print("  SwampCastle Project Setup")
    print(f"{'=' * 55}")
    print()
    print("  SwampCastle organises your project files into labelled")
    print("  groups called 'rooms' under a project label called a")
    print("  'wing'. This config tells 'swampcastle gather' how to")
    print("  classify your files during ingest.")
    print("  You can redo this at any time by rerunning this command.")
    print(f"\n  Proposed wing: {project_name}")
    print(f"  ({total_files} files found)\n")
    print("  Proposed rooms:\n")
    for i, room in enumerate(rooms, 1):
        desc = room["description"]
        print(f"    {i}. {room['name']:20s} <- {desc}")
    print(f"\n{'-' * 55}")


def get_user_approval(rooms: list, project_name: str) -> tuple[list, str]:
    """Interactive approval of proposed rooms and wing name.

    Returns (approved_rooms, wing_name). Empty rooms list means cancelled.
    """
    wing = input(f"  Change wing name? [enter to keep '{project_name}']: ").strip()
    if not wing:
        wing = project_name
    else:
        wing = wing.lower().replace(" ", "_").replace("-", "_")

    print("\n  Options:")
    print("    [A]ccept   Accept proposed rooms")
    print("    [E]dit     Remove or add rooms")
    print("    [C]ancel   Abort without writing config")
    print()

    choice = input("  Your choice [A/e/c]: ").strip().lower()

    if choice in ("c", "cancel"):
        print("  Cancelled. No config written.")
        return [], wing

    if choice in ("e", "edit"):
        print("\n  Current rooms:")
        for i, room in enumerate(rooms):
            print(f"    {i + 1}. {room['name']} -- {room['description']}")
        remove = input("\n  Room numbers to REMOVE (comma-separated, or enter to skip): ").strip()
        if remove:
            to_remove = {int(x.strip()) - 1 for x in remove.split(",") if x.strip().isdigit()}
            rooms = [r for i, r in enumerate(rooms) if i not in to_remove]

        if input("\n  Add any missing rooms? [y/N]: ").strip().lower() == "y":
            while True:
                new_name = (
                    input("  New room name (or enter to stop): ").strip().lower().replace(" ", "_")
                )
                if not new_name:
                    break
                new_desc = (
                    input(f"  Description for '{new_name}': ").strip() or f"Files for {new_name}"
                )
                rooms.append({"name": new_name, "description": new_desc, "keywords": [new_name]})
                print(f"  Added: {new_name}")

    return rooms, wing


def save_config(
    project_dir: str,
    project_name: str,
    rooms: list,
    force: bool = False,
    team: list[str] | None = None,
) -> bool:
    config = {
        "wing": project_name,
    }
    if team:
        config["team"] = team
    config["rooms"] = [
        {
            "name": r["name"],
            "description": r["description"],
            "keywords": sorted(set(r.get("keywords", [r["name"]]))),
        }
        for r in rooms
    ]
    config_path = project_config_path(project_dir)

    if config_path.exists() and not force:
        overwrite = input(f"  {config_path} already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite not in ("y", "yes"):
            print("  Cancelled. Existing config preserved.")
            return False

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"\n  Config saved: {config_path}")
    print("\n  Next step:")
    print(f"    swampcastle gather {project_dir}")
    print(f"\n{'=' * 55}\n")
    return True


def detect_rooms_local(
    project_dir: str,
    yes: bool = False,
    wing: str | None = None,
    team: list[str] | None = None,
):
    """Main entry point for local project setup."""
    project_path = Path(project_dir).expanduser().resolve()
    project_name = wing or project_path.name.lower().replace(" ", "_").replace("-", "_")

    if not project_path.exists():
        print(f"ERROR: Directory not found: {project_dir}")
        sys.exit(1)

    from .miner import scan_project

    files = scan_project(project_dir)

    rooms = detect_rooms_from_folders(project_dir)
    if len(rooms) <= 1:
        rooms = detect_rooms_from_files(project_dir)
    if not rooms:
        rooms = [{"name": "general", "description": "All project files", "keywords": []}]

    print_proposed_structure(project_name, rooms, len(files))

    if yes:
        approved_rooms = rooms
        final_wing = project_name
    else:
        approved_rooms, final_wing = get_user_approval(rooms, project_name)
        if not approved_rooms:
            return

        print("\n  Final config:")
        print(f"    Wing: {final_wing}")
        print(f"    Rooms: {', '.join(r['name'] for r in approved_rooms)}")
        confirm = input("\n  Write .swampcastle.yaml? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            print("  Cancelled. No config written.")
            return

    save_config(project_dir, final_wing, approved_rooms, force=yes, team=team)
