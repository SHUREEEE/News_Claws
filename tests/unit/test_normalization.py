import pytest
from news_claws.domain.normalization import (
    canonicalize_url,
    content_hash,
    jaccard_similarity,
    normalize_text,
)


def test_canonicalize_url_removes_only_known_tracking_parameters() -> None:
    value = canonicalize_url(
        "HTTPS://Example.COM:443/news/?utm_source=test&id=42&view=full#section"
    )
    assert value == "https://example.com/news?id=42&view=full"


@pytest.mark.parametrize(
    "value",
    ["javascript:alert(1)", "/relative/news", "https://user:secret@example.com/news"],
)
def test_canonicalize_url_rejects_unsafe_article_links(value: str) -> None:
    with pytest.raises(ValueError, match="absolute http/https"):
        canonicalize_url(value)


def test_normalization_and_hash_are_stable() -> None:
    assert normalize_text("Ａ  \n B") == "A B"
    assert content_hash("Ａ", "B") == content_hash("A", " B ")


def test_multilingual_title_similarity_separates_topics() -> None:
    close = jaccard_similarity(
        "海上风电扩容方案带动设备与电网投资",
        "海上风电扩容将带动设备和电网投资",
    )
    unrelated = jaccard_similarity("海上风电扩容方案", "云服务数据出境审查")
    assert close > 0.45
    assert unrelated < 0.1
