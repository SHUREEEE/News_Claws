from pathlib import Path

import pytest

from scripts.prepare_deployment_env import IMAGE, prepare_environment
from scripts.validate_production_env import parse_env

FULL_SHA = "a" * 40
BCRYPT_HASH = "$2a$14$" + "b" * 53


def production_lines(*, include_image: bool = True) -> list[str]:
    lines = [
        "APP_ENV=prod",
        "DATABASE_URL=sqlite:////data/analysis.db",
        "ADMIN_TOKEN=a-unique-production-token-that-is-long-enough",
        "DOMAIN=news.company.org",
        "ALLOWED_HOSTS=news.company.org,127.0.0.1,localhost",
        "BASIC_AUTH_USER=newsadmin",
        f"BASIC_AUTH_HASH='{BCRYPT_HASH}'",
        "OUTBOUND_USER_AGENT=NewsClaws/0.1 (contact: ops@company.org)",
        "SEED_DEMO=false",
    ]
    if include_image:
        lines[2:2] = [
            "NEWS_CLAWS_IMAGE=stale.example.invalid/news-claws",
            "NEWS_CLAWS_IMAGE_TAG=0123456789abcdef0123456789abcdef01234567",
        ]
    return lines


def write_environment(path: Path, *, include_image: bool = True) -> None:
    path.write_text(
        "\n".join(production_lines(include_image=include_image)) + "\n", encoding="utf-8"
    )


def test_prepare_environment_overrides_image_and_preserves_quoted_secrets(tmp_path: Path) -> None:
    source = tmp_path / "source.env"
    destination = tmp_path / "prepared.env"
    write_environment(source)

    values = prepare_environment(source, destination, FULL_SHA)

    assert values["NEWS_CLAWS_IMAGE"] == IMAGE
    assert values["NEWS_CLAWS_IMAGE_TAG"] == FULL_SHA
    assert parse_env(destination) == values
    assert f"BASIC_AUTH_HASH='{BCRYPT_HASH}'" in destination.read_text(encoding="utf-8")


def test_prepare_environment_adds_missing_image_fields(tmp_path: Path) -> None:
    source = tmp_path / "source.env"
    destination = tmp_path / "prepared.env"
    write_environment(source, include_image=False)

    prepare_environment(source, destination, FULL_SHA)
    values = parse_env(destination)

    assert values["NEWS_CLAWS_IMAGE"] == IMAGE
    assert values["NEWS_CLAWS_IMAGE_TAG"] == FULL_SHA


@pytest.mark.parametrize("image_sha", ["latest", "a" * 39, "A" * 40, "g" * 40])
def test_prepare_environment_rejects_noncanonical_image_sha(tmp_path: Path, image_sha: str) -> None:
    source = tmp_path / "source.env"
    destination = tmp_path / "prepared.env"
    write_environment(source)

    with pytest.raises(ValueError, match="full 40-character lowercase Git SHA"):
        prepare_environment(source, destination, image_sha)

    assert not destination.exists()


def test_prepare_environment_fails_closed_on_other_placeholders(tmp_path: Path) -> None:
    source = tmp_path / "source.env"
    destination = tmp_path / "prepared.env"
    lines = production_lines()
    lines[lines.index("DOMAIN=news.company.org")] = "DOMAIN=news.example.com"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="DOMAIN must be a real DNS hostname"):
        prepare_environment(source, destination, FULL_SHA)

    assert not destination.exists()
