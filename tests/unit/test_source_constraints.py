from types import SimpleNamespace

import pytest
from news_claws.schemas import SourceUpdate
from news_claws.services import update_source


class CommitOnlySession:
    def commit(self) -> None:
        raise AssertionError("invalid source updates must fail before commit")


def test_update_cannot_convert_source_to_website_without_newsplease() -> None:
    source = SimpleNamespace(
        is_demo=False,
        method="rss",
        parser="auto",
        content_policy="metadata_and_excerpt",
    )

    with pytest.raises(ValueError, match="parser=news-please"):
        update_source(CommitOnlySession(), source, SourceUpdate(method="website"))


def test_update_cannot_make_website_source_metadata_only() -> None:
    source = SimpleNamespace(
        is_demo=False,
        method="website",
        parser="news-please",
        content_policy="metadata_and_excerpt",
    )

    with pytest.raises(ValueError, match="excerpt-enabled"):
        update_source(
            CommitOnlySession(),
            source,
            SourceUpdate(content_policy="metadata_only"),
        )
