"""
sweep.py — Idempotent transcript sweep across both clients' session directories.

Orchestrates mine_convos (thin ingest: chunk + embed + timestamps + mechanical
routing — no LLM) over every project subdirectory of the Claude Code and pi
transcript roots. Idempotency comes from the miner itself: unchanged files are
skipped via source_mtime, changed files are purged and re-filed under
deterministic drawer IDs.

Designed to run unattended from a systemd user timer. A project directory that
fails does not stop the sweep, but any failure makes the run exit non-zero so
the service unit lands in failure state — never a silent skip.
"""

import os
from pathlib import Path

from swampcastle.mining.convo import mine_convos

DEFAULT_ROOTS = (
    ("claude-code", "~/.claude/projects"),
    ("pi", "~/.pi/agent/sessions"),
)

SERVICE_UNIT = """\
[Unit]
Description=SwampCastle transcript sweep (thin ingest)

[Service]
Type=oneshot
ExecStart=%h/.local/bin/swampcastle sweep
Environment=PYTHONUNBUFFERED=1
Nice=10
IOSchedulingClass=idle
"""

TIMER_UNIT = """\
[Unit]
Description=Run the SwampCastle transcript sweep every 6 hours

[Timer]
OnBootSec=15min
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
"""


def _find_oversize(root: Path) -> list[str]:
    """Transcript files scan_convos silently drops for size — reported loudly here."""
    from swampcastle.mining import convo

    oversize = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in convo.SKIP_DIRS]
        for filename in filenames:
            filepath = Path(dirpath) / filename
            if filepath.suffix.lower() not in convo.CONVO_EXTENSIONS:
                continue
            if filepath.is_symlink():
                continue
            try:
                if filepath.stat().st_size > convo.MAX_FILE_SIZE:
                    oversize.append(str(filepath))
            except OSError:
                continue
    return oversize


def sweep_transcripts(
    palace_path: str,
    roots=None,
    storage_factory=None,
    dry_run: bool = False,
) -> dict:
    """Sweep every project subdirectory of each transcript root into the palace.

    Returns a summary dict; callers decide the exit code from projects_failed.
    """
    if roots is None:
        roots = [(name, Path(p).expanduser()) for name, p in DEFAULT_ROOTS]
    else:
        roots = [(name, Path(p).expanduser()) for name, p in roots]

    summary = {
        "projects_swept": 0,
        "projects_failed": [],
        "roots_missing": [],
        "oversize": [],
    }

    for name, root in roots:
        if not root.is_dir():
            summary["roots_missing"].append(name)
            continue

        summary["oversize"].extend(_find_oversize(root))

        for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            try:
                mine_convos(
                    str(project_dir),
                    palace_path,
                    dry_run=dry_run,
                    storage_factory=storage_factory,
                )
                summary["projects_swept"] += 1
            except Exception as e:  # noqa: BLE001 — one bad project must not stop the sweep
                summary["projects_failed"].append(f"{project_dir}: {e}")

    return summary


def install_timer(unit_dir=None, run_systemctl: bool = True) -> list[Path]:
    """Write the sweep service + timer units and enable the timer."""
    if unit_dir is None:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir = Path(unit_dir)
    unit_dir.mkdir(parents=True, exist_ok=True)

    service_path = unit_dir / "swampcastle-sweep.service"
    timer_path = unit_dir / "swampcastle-sweep.timer"
    service_path.write_text(SERVICE_UNIT)
    timer_path.write_text(TIMER_UNIT)

    if run_systemctl:
        import subprocess

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "swampcastle-sweep.timer"],
            check=True,
        )

    return [service_path, timer_path]
