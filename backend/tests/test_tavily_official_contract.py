"""Exercise the installed official tools, replacing only their HTTP transport.

Adapter-only fakes cannot prove that invocation parameters reach Tavily. These
tests use no real credentials, DNS resolution, or provider requests.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_tavily import TavilyExtract, TavilySearch
from pydantic import SecretStr

from app.clients.tavily import (
    AdaptiveExtractInput,
    AdaptiveSearchInput,
    AdaptiveTavilyExtract,
    AdaptiveTavilySearch,
)


async def identity_url(value: str) -> str:
    return value


@pytest.fixture
def provider_status(request) -> int:
    return getattr(request, "param", 200)


@pytest.fixture
def recorded_http(monkeypatch, provider_status) -> list[tuple[str, dict[str, Any]]]:
    requests: list[tuple[str, dict[str, Any]]] = []

    class Response:
        status = provider_status
        reason = "offline test response"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def text(self) -> str:
            return json.dumps(
                {
                    "results": [
                        {
                            "title": "Offline test page",
                            "url": "https://example.com/article",
                            "content": "Offline summary",
                            "raw_content": "# Offline test page\nTest body.",
                        }
                    ],
                    "response_time": 0.01,
                }
            )

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def post(self, url: str, *, json: dict[str, Any], headers):
            # Deliberately do not collect headers, even with fake credentials.
            requests.append((url, json))
            return Response()

    monkeypatch.setattr("aiohttp.ClientSession", Session)
    return requests


@pytest.mark.anyio
@pytest.mark.parametrize("strict_language", [False, True])
async def test_official_search_transmits_language_and_dynamic_parameters(
    recorded_http, strict_language: bool
) -> None:
    search = AdaptiveTavilySearch(
        tavily_api_key=SecretStr("offline-test-placeholder"),
        normalize_url=identity_url,
    )

    output = await search.search(
        AdaptiveSearchInput(
            query="杭州 技术交流",
            max_results=3,
            search_depth="advanced",
            content_mode="full",
            country="china",
            language="zh-cn",
            filter_by_language=strict_language,
            include_domains=["example.com"],
            time_range="month",
        )
    )

    assert len(recorded_http) == 1
    url, payload = recorded_http[0]
    assert url.endswith("/search")
    assert payload["language"] == "zh-cn"
    assert payload["filter_by_language"] is strict_language
    assert payload["country"] == "china"
    assert payload["max_results"] == 3
    assert payload["search_depth"] == "advanced"
    assert payload["include_raw_content"] == "markdown"
    assert payload["include_domains"] == ["example.com"]
    assert payload["time_range"] == "month"
    assert payload["include_answer"] is False
    assert payload["include_images"] is False
    assert payload["auto_parameters"] is False
    assert output.results[0].raw_content == "# Offline test page\nTest body."


@pytest.mark.anyio
async def test_official_full_page_extract_omits_relevance_and_chunk_parameters(
    recorded_http,
) -> None:
    extract = AdaptiveTavilyExtract(
        tavily_api_key=SecretStr("offline-test-placeholder"),
        normalize_url=identity_url,
    )

    output = await extract.extract(
        AdaptiveExtractInput(
            urls=["https://example.com/article"],
            extract_depth="advanced",
            full_page=True,
        )
    )

    assert len(recorded_http) == 1
    url, payload = recorded_http[0]
    assert url.endswith("/extract")
    assert payload["urls"] == ["https://example.com/article"]
    assert payload["extract_depth"] == "advanced"
    assert payload["format"] == "markdown"
    assert payload["include_images"] is False
    assert "query" not in payload
    assert "chunks_per_source" not in payload
    assert output.pages[0].raw_content == "# Offline test page\nTest body."


@pytest.mark.anyio
@pytest.mark.parametrize("provider_status", [401, 403, 429, 503], indirect=True)
@pytest.mark.parametrize("tool_type", [TavilySearch, TavilyExtract])
async def test_installed_official_http_error_contract_loses_status_metadata(
    recorded_http, provider_status: int, tool_type
) -> None:
    """Characterize an upstream limitation, not acceptance of application behavior.

    A dependency upgrade that preserves status should fail this characterization
    so the compatibility decision can be revisited instead of silently retained.
    """
    tool = tool_type(tavily_api_key="offline-test-placeholder")
    payload = (
        {"query": "offline test"}
        if tool_type is TavilySearch
        else {"urls": ["https://example.com/article"]}
    )

    result = await tool.ainvoke(payload)

    assert len(recorded_http) == 1
    error = result["error"]
    assert type(error) is Exception
    assert not any(hasattr(error, attr) for attr in ("status", "status_code", "response"))
    assert str(error) == f"Error {provider_status}: offline test response"
