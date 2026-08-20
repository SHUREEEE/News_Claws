import tomllib
from pathlib import Path

from news_claws import __version__
from news_claws.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_package_api_and_project_versions_match() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == __version__ == app.version
