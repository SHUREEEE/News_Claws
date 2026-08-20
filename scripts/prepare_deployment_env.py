from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from scripts.validate_production_env import parse_env, validate

IMAGE = "ghcr.io/shureeee/news_claws"
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def prepare_environment(source: Path, destination: Path, image_sha: str) -> dict[str, str]:
    normalized_sha = image_sha.strip()
    if FULL_SHA.fullmatch(normalized_sha) is None:
        raise ValueError("image_sha must be a full 40-character lowercase Git SHA")

    values = parse_env(source)
    values["NEWS_CLAWS_IMAGE"] = IMAGE
    values["NEWS_CLAWS_IMAGE_TAG"] = normalized_sha
    errors = validate(values)
    if errors:
        raise ValueError("Production environment is invalid:\n- " + "\n- ".join(errors))

    replacements = {
        "NEWS_CLAWS_IMAGE": IMAGE,
        "NEWS_CLAWS_IMAGE_TAG": normalized_sha,
    }
    seen: set[str] = set()
    output_lines: list[str] = []
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in replacements:
                output_lines.append(f"{key}={replacements[key]}")
                seen.add(key)
                continue
        output_lines.append(raw_line)
    for key, value in replacements.items():
        if key not in seen:
            output_lines.append(f"{key}={value}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        destination.chmod(0o600)
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a validated production deployment file")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("image_sha")
    args = parser.parse_args()
    try:
        prepare_environment(args.source, args.destination, args.image_sha)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(args.destination)


if __name__ == "__main__":
    main()
