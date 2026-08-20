from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_alembic_cli_honors_database_url(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "alembic-target.db"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "ADMIN_TOKEN": "migration-test-token",
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "SEED_DEMO": "false",
        }
    )

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert database_path.is_file()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "d542a38f7c10",
        )
        source_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(source)").fetchall()
        }
        assert "parser" in source_columns
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
