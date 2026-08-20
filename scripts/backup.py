from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a consistent SQLite online backup")
    parser.add_argument("--database", type=Path, default=Path("data/analysis.db"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/backups"))
    args = parser.parse_args()
    if not args.database.is_file():
        raise SystemExit(f"Database does not exist: {args.database}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = args.output_dir / f"analysis-{stamp}.db"
    with sqlite3.connect(args.database) as source, sqlite3.connect(destination) as target:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise SystemExit("Backup integrity check failed")
    checksum = sha256(destination)
    destination.with_suffix(".db.sha256").write_text(
        f"{checksum}  {destination.name}\n", encoding="ascii"
    )
    print(destination)


if __name__ == "__main__":
    main()
