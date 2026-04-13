"""Tests for swampcastle.wal — WalWriter audit log."""

import json

from swampcastle.wal import WalWriter


class TestWalWriter:
    def test_write_and_read(self, tmp_path):
        wal = WalWriter(tmp_path / "wal")
        wal.log("add_drawer", {"wing": "test", "room": "r1"})
        entries = wal.read_entries()
        assert len(entries) == 1
        assert entries[0]["operation"] == "add_drawer"
        assert entries[0]["params"]["wing"] == "test"
        assert "timestamp" in entries[0]

    def test_multiple_entries(self, tmp_path):
        wal = WalWriter(tmp_path / "wal")
        wal.log("add_drawer", {"id": "1"})
        wal.log("delete_drawer", {"id": "2"})
        wal.log("kg_add", {"subject": "A"})
        entries = wal.read_entries()
        assert len(entries) == 3
        assert [e["operation"] for e in entries] == [
            "add_drawer",
            "delete_drawer",
            "kg_add",
        ]

    def test_result_field(self, tmp_path):
        wal = WalWriter(tmp_path / "wal")
        wal.log("add_drawer", {"id": "1"}, result={"success": True})
        entries = wal.read_entries()
        assert entries[0]["result"] == {"success": True}

    def test_empty_read(self, tmp_path):
        wal = WalWriter(tmp_path / "wal")
        assert wal.read_entries() == []

    def test_creates_directory(self, tmp_path):
        wal_dir = tmp_path / "nested" / "wal"
        WalWriter(wal_dir)
        assert wal_dir.exists()

    def test_jsonl_format(self, tmp_path):
        wal = WalWriter(tmp_path / "wal")
        wal.log("op1", {"k": "v1"})
        wal.log("op2", {"k": "v2"})
        raw = (tmp_path / "wal" / "write_log.jsonl").read_text()
        lines = [entry for entry in raw.strip().split("\n") if entry]
        assert len(lines) == 2
        for line in lines:
            json.loads(line)

    def test_file_permissions(self, tmp_path):
        import os
        import stat

        wal = WalWriter(tmp_path / "wal")
        wal.log("test", {})
        wal_file = tmp_path / "wal" / "write_log.jsonl"
        mode = stat.S_IMODE(os.stat(wal_file).st_mode)
        assert mode == 0o600
