from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.clients.tavily import (
    AdaptiveExtractInput,
    AdaptiveTavilyExtract,
    PageUnreadableError,
    TavilyAuthenticationError,
    TavilyUnavailableError,
)
from app.services.url_safety import InvalidSourceUrlError


@dataclass
class RecordingExtractFactory:
    outcomes: list[Any]
    init_calls: list[dict[str, Any]] = field(default_factory=list)
    invoke_calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, **kwargs: Any):
        self.init_calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        invoke_calls = self.invoke_calls

        class Tool:
            async def ainvoke(self, payload: dict[str, Any]) -> dict[str, Any]:
                invoke_calls.append(payload)
                if isinstance(outcome, Exception):
                    raise outcome
                if callable(outcome):
                    return await outcome(payload)
                return outcome

        return Tool()


async def identity_url(value: str) -> str:
    if value.endswith(".internal"):
        raise InvalidSourceUrlError("not public")
    return value


def extract_payload(
    *,
    raw_content: str = "# 页面标题\n\n完整页面正文",
    failed_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "results": [
            {
                "url": "https://example.com/guide",
                "raw_content": raw_content,
            }
        ],
        "failed_results": failed_results or [],
        "response_time": 0.8,
        "usage": {"credits": 1},
    }


def adapter(factory: RecordingExtractFactory, **overrides: Any) -> AdaptiveTavilyExtract:
    return AdaptiveTavilyExtract(
        tavily_api_key=SecretStr("secret-key"),
        tool_factory=factory,
        normalize_url=identity_url,
        basic_timeout_seconds=overrides.get("basic_timeout_seconds", 1),
        advanced_timeout_seconds=overrides.get("advanced_timeout_seconds", 1),
        transient_retries=overrides.get("transient_retries", 1),
        page_char_limit=overrides.get("page_char_limit", 120_000),
    )


@pytest.mark.anyio
async def test_direct_page_full_extract_omits_query_and_uses_markdown() -> None:
    factory = RecordingExtractFactory([extract_payload()])
    extract = adapter(factory)

    output = await extract.extract(
        AdaptiveExtractInput(
            urls=["https://example.com/guide"],
            extract_depth="basic",
            full_page=True,
        )
    )

    assert output.pages[0].title == "页面标题"
    assert output.pages[0].raw_content.endswith("完整页面正文")
    assert factory.init_calls == [
        {
            "tavily_api_key": "secret-key",
            "format": "markdown",
            "include_images": False,
            "include_favicon": False,
            "include_usage": True,
            "chunks_per_source": None,
        }
    ]
    assert factory.invoke_calls == [
        {
            "urls": ["https://example.com/guide"],
            "extract_depth": "basic",
            "include_images": False,
        }
    ]


@pytest.mark.anyio
async def test_relevance_extract_passes_query_and_chunks_per_source() -> None:
    factory = RecordingExtractFactory([extract_payload()])
    extract = adapter(factory)

    await extract.extract(
        AdaptiveExtractInput(
            urls=["https://example.com/guide"],
            extract_depth="advanced",
            full_page=False,
            query="Harness Engineering feedback loops",
            chunks_per_source=5,
        )
    )

    assert factory.init_calls[0]["chunks_per_source"] == 5
    assert factory.invoke_calls[0]["query"] == "Harness Engineering feedback loops"


def test_extract_input_enforces_url_count_and_full_page_query_rules() -> None:
    with pytest.raises(ValidationError):
        AdaptiveExtractInput(
            urls=[
                "https://one.example",
                "https://two.example",
                "https://three.example",
                "https://four.example",
            ]
        )

    with pytest.raises(ValidationError, match="整页"):
        AdaptiveExtractInput(
            urls=["https://example.com"],
            full_page=True,
            query="only relevant chunks",
        )


@pytest.mark.anyio
async def test_urls_are_safety_checked_before_official_tool_call() -> None:
    factory = RecordingExtractFactory([extract_payload()])

    with pytest.raises(InvalidSourceUrlError):
        await adapter(factory).extract(
            AdaptiveExtractInput(urls=["http://private.internal"])
        )

    assert factory.init_calls == []


@pytest.mark.anyio
async def test_failed_or_oversized_page_is_normalized_as_unreadable() -> None:
    failed = RecordingExtractFactory(
        [
            {
                "results": [],
                "failed_results": [
                    {"url": "https://example.com/guide", "error": "blocked"}
                ],
            }
        ]
    )
    with pytest.raises(PageUnreadableError, match="无法读取"):
        await adapter(failed, transient_retries=0).extract(
            AdaptiveExtractInput(urls=["https://example.com/guide"], full_page=True)
        )

    oversized = RecordingExtractFactory([extract_payload(raw_content="x" * 101)])
    with pytest.raises(PageUnreadableError, match="过大"):
        await adapter(oversized, page_char_limit=100).extract(
            AdaptiveExtractInput(urls=["https://example.com/guide"], full_page=True)
        )


@pytest.mark.anyio
async def test_extract_timeout_retries_once_but_authentication_does_not() -> None:
    async def slow(_: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return extract_payload()

    slow_factory = RecordingExtractFactory([slow, slow])
    with pytest.raises(TavilyUnavailableError, match="超时"):
        await adapter(
            slow_factory,
            basic_timeout_seconds=0.001,
        ).extract(AdaptiveExtractInput(urls=["https://example.com/guide"]))
    assert len(slow_factory.init_calls) == 2

    auth_factory = RecordingExtractFactory(
        [ValueError("Error 401: invalid api key"), extract_payload()]
    )
    with pytest.raises(TavilyAuthenticationError):
        await adapter(auth_factory).extract(
            AdaptiveExtractInput(urls=["https://example.com/guide"])
        )
    assert len(auth_factory.init_calls) == 1
