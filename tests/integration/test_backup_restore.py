from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path


def test_backup_restore_verifies_checksum_and_integrity(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES ('evidence')")
        connection.commit()

    backup_dir = tmp_path / "backups"
    backup_result = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "backup.py"),
            "--database",
            str(source),
            "--output-dir",
            str(backup_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    backup = Path(backup_result.stdout.strip())
    checksum = backup.with_suffix(backup.suffix + ".sha256")
    assert backup.is_file()
    assert checksum.is_file()

    restored = tmp_path / "restored" / "analysis.db"
    subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "restore.py"),
            "--source",
            str(backup),
            "--target",
            str(restored),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    with sqlite3.connect(restored) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM sample").fetchone() == ("evidence",)

    checksum.write_text("0" * 64 + "  " + backup.name + "\n", encoding="ascii")
    rejected_target = tmp_path / "rejected.db"
    rejected = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "restore.py"),
            "--source",
            str(backup),
            "--target",
            str(rejected_target),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "checksum validation failed" in rejected.stderr
    assert not rejected_target.exists()
