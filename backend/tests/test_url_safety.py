from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.services.url_safety import InvalidSourceUrlError, normalize_public_url


def resolver_for(*addresses: str):
    async def resolve(_: str) -> Sequence[str]:
        return addresses

    return resolve


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "https://user:password@example.com/private",
        "http://localhost/admin",
        "http://service.local/data",
    ],
)
async def test_non_web_credentials_and_local_names_are_rejected(url: str) -> None:
    with pytest.raises(InvalidSourceUrlError):
        await normalize_public_url(url, resolver=resolver_for("93.184.216.34"))


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("url", "resolved"),
    [
        ("http://127.0.0.1", "127.0.0.1"),
        ("http://2130706433", "127.0.0.1"),
        ("http://10.0.0.8", "10.0.0.8"),
        ("http://169.254.169.254/latest/meta-data", "169.254.169.254"),
        ("http://[::1]", "::1"),
        ("http://[fe80::1]", "fe80::1"),
        ("http://[::ffff:127.0.0.1]", "::ffff:127.0.0.1"),
    ],
)
async def test_private_link_local_and_mixed_addresses_are_rejected(
    url: str,
    resolved: str,
) -> None:
    with pytest.raises(InvalidSourceUrlError):
        await normalize_public_url(url, resolver=resolver_for(resolved))


@pytest.mark.anyio
async def test_dns_answer_fails_closed_if_any_address_is_not_public() -> None:
    with pytest.raises(InvalidSourceUrlError, match="公开"):
        await normalize_public_url(
            "https://rebinding.example/article",
            resolver=resolver_for("93.184.216.34", "127.0.0.1"),
        )


@pytest.mark.anyio
async def test_unresolvable_target_fails_closed() -> None:
    async def failed_resolver(_: str) -> Sequence[str]:
        raise OSError("dns unavailable")

    with pytest.raises(InvalidSourceUrlError, match="公开"):
        await normalize_public_url(
            "https://unknown.example/article",
            resolver=failed_resolver,
        )


@pytest.mark.anyio
async def test_url_is_normalized_and_tracking_parameters_are_removed() -> None:
    normalized = await normalize_public_url(
        "HTTPS://Example.COM:443/article?id=42&utm_source=chat&fbclid=abc#section",
        resolver=resolver_for("93.184.216.34"),
    )

    assert normalized == "https://example.com/article?id=42"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query_name",
    ["token", "access_token", "api_key", "signature", "auth", "code"],
)
async def test_sensitive_query_parameters_are_rejected_without_echoing_value(
    query_name: str,
) -> None:
    secret = "must-not-appear"

    with pytest.raises(InvalidSourceUrlError) as captured:
        await normalize_public_url(
            f"https://example.com/article?{query_name}={secret}",
            resolver=resolver_for("93.184.216.34"),
        )

    assert secret not in str(captured.value)


@pytest.mark.anyio
async def test_tavily_visible_final_url_is_checked_with_same_boundary() -> None:
    with pytest.raises(InvalidSourceUrlError):
        await normalize_public_url(
            "http://redirected.internal/result",
            resolver=resolver_for("192.168.1.20"),
        )
