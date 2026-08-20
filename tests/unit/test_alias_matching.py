import pytest
from news_claws.models import EntityAlias
from news_claws.services import _alias_matches


def _alias(value: str, alias_type: str) -> EntityAlias:
    return EntityAlias(entity_id="company_test", alias=value, alias_type=alias_type)


@pytest.mark.parametrize(
    "text",
    [
        "A new policy affects manufacturers",
        "Grade A shares rose after the announcement",
        "The company opened a new plant",
    ],
)
def test_single_letter_ticker_does_not_match_plain_text(text: str) -> None:
    assert not _alias_matches(text, _alias("A", "ticker"))


@pytest.mark.parametrize("text", ["$A rose 3%", "Results improved for (A) this quarter"])
def test_single_letter_ticker_requires_market_notation(text: str) -> None:
    assert _alias_matches(text, _alias("A", "ticker"))


def test_multi_letter_ticker_uses_uppercase_token_boundaries() -> None:
    ticker = _alias("NVDA", "ticker")

    assert _alias_matches("NVDA launches a new accelerator", ticker)
    assert _alias_matches("Shares of $NVDA rose", ticker)
    assert not _alias_matches("NVDAX is a different token", ticker)
    assert not _alias_matches("The article spells nvda in lowercase", ticker)


def test_company_name_match_is_case_insensitive() -> None:
    assert _alias_matches(
        "APPLE INC. announced a supplier agreement",
        _alias("Apple Inc.", "name"),
    )
