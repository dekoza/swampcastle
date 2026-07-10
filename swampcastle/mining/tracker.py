"""
tracker.py — Wayfinder-tracker source adapter.

Ingests wayfinder maps (issues labelled wayfinder:map), their resolved child
tickets, and resolution comments from project trackers as pre-distilled
decision memories: one drawer per closed ticket (title + question +
resolution), room "decisions", wing = repo name, plus one drawer per map body.
Open tickets are skipped — undecided things aren't memories yet.

Forge access shells out to the already-authenticated CLIs: `tea api` for
Gitea (which must run from inside SOME git repo, so a dedicated `git init`-ed
workdir under ~/.swampcastle serves as cwd) and `gh api` for GitHub. Both
forges speak the same issues/comments JSON shape.

Registration lives in ~/.swampcastle/config.json under `tracker_repos` —
structured entries managed by `swampcastle tracker register/list/remove`,
seeded by the project wizard, and consumed by the sweep. The sweep treats
entries as hints, not truth: failures are classified (auth pauses ALL tracker
ingest loudly; a gone repo marks its entry stale after STALE_AFTER consecutive
failures, visibly; transient errors skip once) — never silent.
"""

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from swampcastle import runtime_config

DEFAULT_LABEL = "wayfinder:map"
STALE_AFTER = 3
_PAGE_SIZE = 50
_MAX_PAGES = 40


class TrackerError(Exception):
    """Base for tracker ingest failures."""


class TrackerAuthError(TrackerError):
    """Credential problem — not the repo's fault; pause all tracker ingest."""


class TrackerRepoGoneError(TrackerError):
    """Repo 404s — quarantine this entry after repeated failures."""


class TrackerTransientError(TrackerError):
    """Network hiccup or forge outage — skip this run, no state change."""


def _classify_forge_error(text: str) -> TrackerError:
    lowered = text.lower()
    if any(m in lowered for m in ("401", "403", "unauthorized", "bad credentials", "forbidden")):
        return TrackerAuthError(text.strip())
    if any(m in lowered for m in ("404", "not found")):
        return TrackerRepoGoneError(text.strip())
    return TrackerTransientError(text.strip())


def _tracker_workdir() -> Path:
    """A dedicated git repo so `tea` (which insists on a repo cwd) runs headless."""
    workdir = Path.home() / ".swampcastle" / "tracker-workdir"
    if not (workdir / ".git").is_dir():
        workdir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(workdir)], check=True, capture_output=True)
    return workdir


def _forge_api_get(forge: str, repo: str, path: str):
    """GET an issues-API path via the forge's CLI; both speak the same JSON shape."""
    url = f"repos/{repo}/{path}"
    if forge == "gitea":
        cmd = ["tea", "api", url]
        cwd = str(_tracker_workdir())
    elif forge == "github":
        cmd = ["gh", "api", url]
        cwd = None
    else:
        raise TrackerError(f"Unknown forge: {forge}")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise TrackerTransientError(str(e)) from e
    if proc.returncode != 0:
        raise _classify_forge_error(proc.stderr or proc.stdout or f"exit {proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise TrackerTransientError(f"unparseable forge response: {e}") from e


# ── remote detection ─────────────────────────────────────────────────


def parse_remote_url(url: str, gitea_hosts: list[str]) -> tuple[str, str] | None:
    """Map a git remote URL to (forge, owner/repo), or None if no known forge."""
    cleaned = url.strip().removesuffix(".git")
    segments = [s for s in re.split(r"[:/]+", cleaned) if s]
    if len(segments) < 2:
        return None
    repo = f"{segments[-2]}/{segments[-1]}"
    if "github.com" in cleaned:
        return ("github", repo)
    for host in gitea_hosts:
        # SSH remotes use the SSH port, HTTP the web port — match hostname only.
        hostname = host.split(":")[0]
        if hostname and hostname in cleaned:
            return ("gitea", repo)
    return None


def _gitea_hosts_from_tea_config() -> list[str]:
    config_path = Path.home() / ".config" / "tea" / "config.yml"
    if not config_path.is_file():
        return []
    try:
        import yaml

        data = yaml.safe_load(config_path.read_text())
        hosts = []
        for login in data.get("logins", []):
            for key in ("url", "ssh_host"):
                value = str(login.get(key, ""))
                host = value.split("://")[-1].strip("/")
                if host:
                    hosts.append(host)
        return hosts
    except Exception:
        return []


def detect_tracker_repo(project_dir: str) -> tuple[str, str] | None:
    """Inspect a project's git remotes for a known forge."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_dir), "remote", "-v"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    gitea_hosts = _gitea_hosts_from_tea_config()
    github_by_remote: dict[str, tuple[str, str]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        parsed = parse_remote_url(parts[1], gitea_hosts)
        if parsed is None:
            continue
        if parsed[0] == "gitea":
            return parsed  # LLM-work tracking lives on Gitea; prefer it
        github_by_remote.setdefault(parts[0], parsed)
    if not github_by_remote:
        return None
    # Prefer origin — other remotes are typically upstreams/mirrors, not ours.
    return github_by_remote.get("origin") or next(iter(github_by_remote.values()))


def probe_wayfinder_map(forge: str, repo: str, label: str = DEFAULT_LABEL) -> bool:
    issues = _forge_api_get(forge, repo, f"issues?labels={label}&state=all&limit=1&type=issues")
    return bool(issues)


# ── registry ─────────────────────────────────────────────────────────


def list_tracker_repos() -> list[dict]:
    config = runtime_config.load_runtime_config()
    return config.get("tracker_repos", [])


def register_tracker_repo(forge: str, repo: str, label: str = DEFAULT_LABEL) -> bool:
    """Add an entry; returns False if the repo is already registered."""
    config = runtime_config.load_runtime_config()
    entries = config.setdefault("tracker_repos", [])
    if any(e.get("repo") == repo for e in entries):
        return False
    entries.append(
        {
            "forge": forge,
            "repo": repo,
            "label": label,
            "state": "active",
            "last_ok": None,
            "consecutive_failures": 0,
        }
    )
    runtime_config.save_runtime_config(config)
    return True


def remove_tracker_repo(repo: str) -> bool:
    config = runtime_config.load_runtime_config()
    entries = config.get("tracker_repos", [])
    remaining = [e for e in entries if e.get("repo") != repo]
    if len(remaining) == len(entries):
        return False
    config["tracker_repos"] = remaining
    runtime_config.save_runtime_config(config)
    return True


def _update_entry(repo: str, **fields) -> None:
    config = runtime_config.load_runtime_config()
    for entry in config.get("tracker_repos", []):
        if entry.get("repo") == repo:
            entry.update(fields)
    runtime_config.save_runtime_config(config)


# ── ingest ───────────────────────────────────────────────────────────

_MAP_REF_RE = re.compile(r"^Map:\s*#(\d+)\s*$", re.MULTILINE)
_BOOKKEEPING_RE = re.compile(r"^(Map|Blocked by):\s*#\d+\s*$\n?", re.MULTILINE)


def build_ticket_content(issue: dict, resolution: str) -> str:
    body = _BOOKKEEPING_RE.sub("", issue.get("body") or "").strip()
    parts = [f"# {issue.get('title', '')}", body]
    if resolution:
        parts.append(resolution.strip())
    return "\n\n".join(p for p in parts if p)


def _wing_for_repo(repo: str) -> str:
    return repo.split("/")[-1].lower().replace("-", "_").replace(" ", "_")


def _drawer_id(wing: str, html_url: str) -> str:
    digest = hashlib.sha256(html_url.encode()).hexdigest()[:24]
    return f"drawer_{wing}_decisions_{digest}"


def _upsert_if_changed(collection, wing: str, issue: dict, content: str, dry_run: bool) -> bool:
    """Upsert one decision drawer; returns True if (re)filed, False if unchanged."""
    html_url = issue["html_url"]
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    if collection is not None:
        existing = collection.get(where={"source_file": html_url}, limit=1)
        metas = existing.get("metadatas") or []
        if existing.get("ids") and metas and metas[0].get("content_hash") == content_hash:
            return False
    if dry_run or collection is None:
        return True
    collection.upsert(
        documents=[content],
        ids=[_drawer_id(wing, html_url)],
        metadatas=[
            {
                "wing": wing,
                "room": "decisions",
                "source_file": html_url,
                "ingest_mode": "tracker",
                "added_by": "swampcastle",
                "filed_at": datetime.now().isoformat(),
                "closed_at": issue.get("closed_at") or "",
                "content_hash": content_hash,
            }
        ],
    )
    return True


def _fetch_all_issues(forge: str, repo: str) -> list[dict]:
    issues = []
    for page in range(1, _MAX_PAGES + 1):
        batch = _forge_api_get(
            forge, repo, f"issues?state=all&page={page}&limit={_PAGE_SIZE}&type=issues"
        )
        if not batch:
            break
        # Gitea puts "pull_request": null on plain issues — drop only real PRs.
        issues.extend(i for i in batch if isinstance(i, dict) and not i.get("pull_request"))
    return issues


def ingest_tracker_repo(
    forge: str,
    repo: str,
    collection=None,
    label: str = DEFAULT_LABEL,
    dry_run: bool = False,
) -> dict:
    """Ingest one repo's wayfinder maps + resolved tickets as decision drawers."""
    wing = _wing_for_repo(repo)
    maps = _forge_api_get(forge, repo, f"issues?labels={label}&state=all&type=issues&limit=50")
    maps = [m for m in maps if isinstance(m, dict)]
    map_numbers = {m["number"] for m in maps}

    drawers = 0
    skipped = 0

    for map_issue in maps:
        content = build_ticket_content(map_issue, "")
        if _upsert_if_changed(collection, wing, map_issue, content, dry_run):
            drawers += 1
        else:
            skipped += 1

    if map_numbers:
        for issue in _fetch_all_issues(forge, repo):
            if issue["number"] in map_numbers:
                continue
            refs = {int(n) for n in _MAP_REF_RE.findall(issue.get("body") or "")}
            if not refs & map_numbers:
                continue
            if issue.get("state") != "closed":
                continue  # open tickets aren't memories yet
            comments = _forge_api_get(forge, repo, f"issues/{issue['number']}/comments")
            resolution = comments[-1].get("body", "") if comments else ""
            content = build_ticket_content(issue, resolution)
            if _upsert_if_changed(collection, wing, issue, content, dry_run):
                drawers += 1
            else:
                skipped += 1

    return {"drawers": drawers, "skipped": skipped}


# ── sweep integration ────────────────────────────────────────────────


def sweep_trackers(collection=None, dry_run: bool = False) -> dict:
    """Ingest every active registered tracker; classify failures, never silent."""
    summary = {"swept": 0, "drawers": 0, "failed": [], "stale": [], "auth_failed": False}
    for entry in list_tracker_repos():
        repo = entry.get("repo", "")
        if entry.get("state") != "active":
            summary["stale"].append(repo)
            continue
        try:
            result = ingest_tracker_repo(
                entry.get("forge", ""),
                repo,
                collection=collection,
                label=entry.get("label", DEFAULT_LABEL),
                dry_run=dry_run,
            )
        except TrackerAuthError as e:
            summary["auth_failed"] = True
            summary["failed"].append(f"{repo}: auth: {e}")
            break  # credentials are global — stop instead of failing every entry
        except TrackerError as e:
            failures = int(entry.get("consecutive_failures", 0)) + 1
            fields = {"consecutive_failures": failures}
            if isinstance(e, TrackerRepoGoneError) and failures >= STALE_AFTER:
                fields["state"] = "stale"
            _update_entry(repo, **fields)
            summary["failed"].append(f"{repo}: {e}")
            continue
        summary["swept"] += 1
        summary["drawers"] += result.get("drawers", 0)
        if not dry_run:
            _update_entry(repo, consecutive_failures=0, last_ok=datetime.now().isoformat())
    return summary
