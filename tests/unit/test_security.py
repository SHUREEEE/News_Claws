import pytest
from news_claws.domain.security import (
    UnsafeUrlError,
    validate_public_http_url,
    validate_public_ip,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "https://user:password@example.com/feed",
    ],
)
def test_private_or_credentialed_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_http_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_non_public_connected_addresses_are_rejected(address: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_public_ip(address)
