from __future__ import annotations

import argparse
import hashlib
import secrets
import sqlite3
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(source: Path, checksum_path: Path) -> None:
    if not checksum_path.is_file():
        raise SystemExit(f"Backup checksum does not exist: {checksum_path}")
    parts = checksum_path.read_text(encoding="ascii").strip().split()
    if not parts:
        raise SystemExit("Backup checksum file is empty")
    expected = parts[0].lower()
    actual = sha256(source)
    if not secrets.compare_digest(expected, actual):
        raise SystemExit("Backup checksum validation failed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a News Claws backup to a new path")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--checksum",
        type=Path,
        help="SHA-256 sidecar; defaults to SOURCE.db.sha256",
    )
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"Backup does not exist: {args.source}")
    if args.target.exists():
        raise SystemExit("Target already exists; restore refuses to overwrite data")
    checksum_path = args.checksum or args.source.with_suffix(args.source.suffix + ".sha256")
    verify_checksum(args.source, checksum_path)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(f"file:{args.source.resolve()}?mode=ro", uri=True) as source:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("Source backup integrity check failed")
            with sqlite3.connect(args.target) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise SystemExit("Restored database integrity check failed")
    except BaseException:
        if args.target.exists():
            args.target.unlink()
        raise
    print(args.target)


if __name__ == "__main__":
    main()
