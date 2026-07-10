"""Tests for the wayfinder-tracker source adapter."""

import pytest

from swampcastle.mining import tracker as tracker_mod
from swampcastle.mining.tracker import (
    TrackerAuthError,
    TrackerRepoGoneError,
    _classify_forge_error,
    build_ticket_content,
    ingest_tracker_repo,
    list_tracker_repos,
    parse_remote_url,
    register_tracker_repo,
    remove_tracker_repo,
    sweep_trackers,
)

GITEA_HOSTS = ["192.168.129.37:30008"]


# --- parse_remote_url ---


def test_parse_github_https():
    assert parse_remote_url("https://github.com/dekoza/swampcastle.git", GITEA_HOSTS) == (
        "github",
        "dekoza/swampcastle",
    )


def test_parse_github_ssh():
    assert parse_remote_url("git@github.com:dekoza/swampcastle.git", GITEA_HOSTS) == (
        "github",
        "dekoza/swampcastle",
    )


def test_parse_gitea_http():
    assert parse_remote_url("http://192.168.129.37:30008/minder/swampcastle.git", GITEA_HOSTS) == (
        "gitea",
        "minder/swampcastle",
    )


def test_parse_gitea_ssh():
    assert parse_remote_url("git@192.168.129.37:30008:minder/swampcastle.git", GITEA_HOSTS) == (
        "gitea",
        "minder/swampcastle",
    )


def test_parse_unknown_host():
    assert parse_remote_url("https://gitlab.com/x/y.git", GITEA_HOSTS) is None


# --- error taxonomy ---


def test_classify_auth_errors():
    for text in ("HTTP 401", "Unauthorized", "Bad credentials", "403 Forbidden"):
        assert isinstance(_classify_forge_error(text), TrackerAuthError)


def test_classify_repo_gone():
    for text in ("HTTP 404", "Not Found"):
        assert isinstance(_classify_forge_error(text), TrackerRepoGoneError)


def test_classify_transient():
    err = _classify_forge_error("connection timed out")
    assert not isinstance(err, (TrackerAuthError, TrackerRepoGoneError))


# --- record shape ---


def test_build_ticket_content_joins_title_question_resolution():
    issue = {"title": "Decide X", "body": "## Question\n\nWhat about X?"}
    content = build_ticket_content(issue, "## Resolution\n\nWe chose Y.")
    assert "Decide X" in content
    assert "What about X?" in content
    assert "We chose Y." in content


# --- registry ---


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    monkeypatch.setattr("swampcastle.runtime_config.runtime_config_path", lambda: cfg)
    monkeypatch.setattr("swampcastle.runtime_config.ensure_runtime_config", lambda: cfg)
    return cfg


def test_register_list_remove_roundtrip(tmp_config):
    assert register_tracker_repo("gitea", "minder/swampcastle") is True
    assert register_tracker_repo("gitea", "minder/swampcastle") is False  # idempotent
    entries = list_tracker_repos()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["forge"] == "gitea"
    assert entry["repo"] == "minder/swampcastle"
    assert entry["label"] == "wayfinder:map"
    assert entry["state"] == "active"
    assert remove_tracker_repo("minder/swampcastle") is True
    assert list_tracker_repos() == []


# --- ingest ---


class FakeCollection:
    def __init__(self):
        self.rows = {}

    def upsert(self, documents, ids, metadatas):
        for doc, id_, meta in zip(documents, ids, metadatas):
            self.rows[id_] = {"document": doc, "metadata": meta}

    def get(self, where=None, ids=None, limit=None, include=None):
        found_ids, metas = [], []
        for id_, row in self.rows.items():
            if ids is not None and id_ not in ids:
                continue
            if where and not all(row["metadata"].get(k) == v for k, v in where.items()):
                continue
            found_ids.append(id_)
            metas.append(row["metadata"])
            if limit and len(found_ids) >= limit:
                break
        return {"ids": found_ids, "metadatas": metas}

    def delete(self, ids):
        for id_ in ids:
            self.rows.pop(id_, None)


MAP_ISSUE = {
    "number": 14,
    "title": "Wayfinder map: Milestone A",
    "body": "## Destination\n\nMilestone A executed.",
    "state": "open",
    "html_url": "http://forge/minder/swampcastle/issues/14",
    "closed_at": None,
    "labels": [{"name": "wayfinder:map"}],
}

CLOSED_TICKET = {
    "number": 16,
    "title": "Decide the packaging story",
    "body": "Map: #14\n\n## Question\n\npipx or uv?",
    "state": "closed",
    "html_url": "http://forge/minder/swampcastle/issues/16",
    "closed_at": "2026-07-10T12:00:00Z",
    "labels": [{"name": "wayfinder:grilling"}],
    "pull_request": None,  # Gitea sets this key to null on plain issues
}

REAL_PR = {
    "number": 50,
    "title": "Some pull request",
    "body": "Map: #14",
    "state": "closed",
    "html_url": "http://forge/minder/swampcastle/pulls/50",
    "closed_at": "2026-07-10T12:00:00Z",
    "labels": [],
    "pull_request": {"merged": True},
}

OPEN_TICKET = {
    "number": 22,
    "title": "Verify the SLO",
    "body": "Map: #14\n\n## Question\n\nDoes it work?",
    "state": "open",
    "html_url": "http://forge/minder/swampcastle/issues/22",
    "closed_at": None,
    "labels": [{"name": "wayfinder:task"}],
}

UNRELATED_ISSUE = {
    "number": 99,
    "title": "User bug report",
    "body": "Something broke",
    "state": "closed",
    "html_url": "http://forge/minder/swampcastle/issues/99",
    "closed_at": "2026-07-01T00:00:00Z",
    "labels": [],
}


def _fake_api(pages):
    """Return a _forge_api_get replacement serving canned responses by path prefix."""

    def api(forge, repo, path):
        for prefix, response in pages.items():
            if path.startswith(prefix):
                return response
        return []

    return api


@pytest.fixture
def fake_forge(monkeypatch):
    def install(comments_16=None):
        pages = {
            "issues?labels=": [MAP_ISSUE],
            "issues?state=all&page=1": [
                MAP_ISSUE,
                CLOSED_TICKET,
                OPEN_TICKET,
                UNRELATED_ISSUE,
                REAL_PR,
            ],
            "issues?state=all&page=2": [],
            "issues/16/comments": comments_16
            if comments_16 is not None
            else [{"body": "## Resolution\n\npipx it is."}],
        }
        monkeypatch.setattr(tracker_mod, "_forge_api_get", _fake_api(pages))

    return install


def test_ingest_creates_map_and_closed_ticket_drawers(fake_forge):
    fake_forge()
    coll = FakeCollection()
    result = ingest_tracker_repo("gitea", "minder/swampcastle", collection=coll)
    assert result["drawers"] == 2  # map body + closed ticket; open + unrelated skipped
    contents = [r["document"] for r in coll.rows.values()]
    assert any("pipx it is." in c for c in contents)
    assert any("Milestone A executed." in c for c in contents)
    metas = [r["metadata"] for r in coll.rows.values()]
    assert all(m["room"] == "decisions" for m in metas)
    assert all(m["ingest_mode"] == "tracker" for m in metas)
    assert all(m["wing"] == "swampcastle" for m in metas)


def test_ingest_idempotent_second_run(fake_forge):
    fake_forge()
    coll = FakeCollection()
    ingest_tracker_repo("gitea", "minder/swampcastle", collection=coll)
    result = ingest_tracker_repo("gitea", "minder/swampcastle", collection=coll)
    assert result["drawers"] == 0
    assert result["skipped"] == 2


def test_ingest_refiles_edited_resolution(fake_forge):
    fake_forge()
    coll = FakeCollection()
    ingest_tracker_repo("gitea", "minder/swampcastle", collection=coll)
    fake_forge(comments_16=[{"body": "## Resolution\n\nActually uv tool."}])
    result = ingest_tracker_repo("gitea", "minder/swampcastle", collection=coll)
    assert result["drawers"] == 1  # only the edited ticket re-filed
    contents = [r["document"] for r in coll.rows.values()]
    assert any("Actually uv tool." in c for c in contents)
    assert not any("pipx it is." in c for c in contents)  # same ID, replaced


# --- sweep integration ---


def test_sweep_trackers_marks_stale_after_failures(tmp_config, monkeypatch):
    register_tracker_repo("gitea", "gone/repo")

    def raise_gone(forge, repo, collection=None, label=None, dry_run=False):
        raise TrackerRepoGoneError("404")

    monkeypatch.setattr(tracker_mod, "ingest_tracker_repo", raise_gone)
    for _ in range(tracker_mod.STALE_AFTER):
        summary = sweep_trackers(collection=None)
    entry = list_tracker_repos()[0]
    assert entry["state"] == "stale"
    assert "gone/repo" in str(summary["failed"])


def test_sweep_trackers_auth_failure_stops_all(tmp_config, monkeypatch):
    register_tracker_repo("gitea", "a/one")
    register_tracker_repo("gitea", "a/two")
    calls = []

    def raise_auth(forge, repo, collection=None, label=None, dry_run=False):
        calls.append(repo)
        raise TrackerAuthError("401")

    monkeypatch.setattr(tracker_mod, "ingest_tracker_repo", raise_auth)
    summary = sweep_trackers(collection=None)
    assert summary["auth_failed"] is True
    assert len(calls) == 1  # stopped after the first auth failure
    # entries NOT marked stale — auth is not the repo's fault
    assert all(e["state"] == "active" for e in list_tracker_repos())


def test_sweep_trackers_skips_stale_entries(tmp_config, monkeypatch):
    register_tracker_repo("gitea", "a/one")
    entries = list_tracker_repos()
    entries[0]["state"] = "stale"
    from swampcastle.runtime_config import load_runtime_config, save_runtime_config

    cfg = load_runtime_config()
    cfg["tracker_repos"] = entries
    save_runtime_config(cfg)

    calls = []
    monkeypatch.setattr(
        tracker_mod,
        "ingest_tracker_repo",
        lambda *a, **kw: calls.append(a) or {"drawers": 0, "skipped": 0},
    )
    summary = sweep_trackers(collection=None)
    assert calls == []
    assert "a/one" in str(summary["stale"])


def test_parse_gitea_ssh_different_port():
    """SSH remotes use the SSH port; match the gitea host by hostname, not host:port."""
    assert parse_remote_url(
        "ssh://git@192.168.129.37:30009/minder/swampcastle.git", GITEA_HOSTS
    ) == ("gitea", "minder/swampcastle")


def test_detect_prefers_gitea_then_origin(monkeypatch, tmp_path):
    remotes = (
        "mempalace\tgit@github.com:MemPalace/mempalace.git (fetch)\n"
        "origin\tgit@github.com:dekoza/swampcastle.git (fetch)\n"
    )

    class FakeProc:
        returncode = 0
        stdout = remotes

    monkeypatch.setattr(tracker_mod.subprocess, "run", lambda *a, **kw: FakeProc())
    monkeypatch.setattr(tracker_mod, "_gitea_hosts_from_tea_config", lambda: [])
    assert tracker_mod.detect_tracker_repo(".") == ("github", "dekoza/swampcastle")


def test_detect_gitea_wins_over_origin(monkeypatch):
    remotes = (
        "origin\tgit@github.com:dekoza/swampcastle.git (fetch)\n"
        "gitea\tssh://git@192.168.129.37:30009/minder/swampcastle.git (fetch)\n"
    )

    class FakeProc:
        returncode = 0
        stdout = remotes

    monkeypatch.setattr(tracker_mod.subprocess, "run", lambda *a, **kw: FakeProc())
    monkeypatch.setattr(
        tracker_mod, "_gitea_hosts_from_tea_config", lambda: ["192.168.129.37:30008"]
    )
    assert tracker_mod.detect_tracker_repo(".") == ("gitea", "minder/swampcastle")
