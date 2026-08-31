from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.clients.tavily import (
    AdaptiveSearchInput,
    AdaptiveTavilySearch,
    TavilyAuthenticationError,
    TavilyUnavailableError,
)
from app.services.url_safety import InvalidSourceUrlError


async def identity_url(value: str) -> str:
    return value


@dataclass
class RecordingSearchFactory:
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


def result_payload(*, raw_content: str | None = None) -> dict[str, Any]:
    return {
        "results": [
            {
                "title": "官方文档",
                "url": "https://docs.example.com/current",
                "content": "当前知识摘要",
                "score": 0.95,
                "published_date": "2026-08-01T00:00:00Z",
                "raw_content": raw_content,
            }
        ],
        "response_time": 0.42,
        "usage": {"credits": 1},
    }


def adapter(factory: RecordingSearchFactory, **overrides: Any) -> AdaptiveTavilySearch:
    return AdaptiveTavilySearch(
        tavily_api_key=SecretStr("secret-key"),
        tool_factory=factory,
        normalize_url=identity_url,
        timeout_seconds=overrides.get("timeout_seconds", 1),
        transient_retries=overrides.get("transient_retries", 1),
    )


@pytest.mark.anyio
async def test_summary_search_maps_static_and_dynamic_official_parameters() -> None:
    factory = RecordingSearchFactory([result_payload()])
    search = adapter(factory)

    output = await search.search(
        AdaptiveSearchInput(
            query="杭州 低空经济 2026",
            content_mode="summary",
            search_depth="basic",
            max_results=5,
            topic="general",
            time_range="month",
            include_domains=["gov.cn"],
            exclude_domains=["example-spam.com"],
            country="china",
            language="zh-cn",
        )
    )

    assert output.results[0].title == "官方文档"
    assert output.results[0].raw_content is None
    assert factory.init_calls == [
        {
            "tavily_api_key": "secret-key",
            "max_results": 5,
            "topic": "general",
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_image_descriptions": False,
            "auto_parameters": False,
            "country": "china",
            "include_usage": True,
        }
    ]
    assert factory.invoke_calls == [
        {
            "query": "杭州 低空经济 2026",
            "search_depth": "basic",
            "time_range": "month",
            "include_domains": ["gov.cn"],
            "exclude_domains": ["example-spam.com"],
            "language": "zh-cn",
            "filter_by_language": False,
        }
    ]


@pytest.mark.anyio
async def test_full_search_uses_markdown_and_is_limited_to_three_results() -> None:
    factory = RecordingSearchFactory([result_payload(raw_content="# 全文")])
    search = adapter(factory)

    output = await search.search(
        AdaptiveSearchInput(
            query="Harness Engineering AI agents",
            content_mode="full",
            search_depth="advanced",
            max_results=3,
        )
    )

    assert output.results[0].raw_content == "# 全文"
    assert factory.init_calls[0]["include_raw_content"] == "markdown"
    assert factory.init_calls[0]["max_results"] == 3

    with pytest.raises(ValidationError, match="全文"):
        AdaptiveSearchInput(
            query="complex",
            content_mode="full",
            search_depth="advanced",
            max_results=4,
        )


def test_search_input_rejects_invalid_country_language_and_date_combinations() -> None:
    with pytest.raises(ValidationError, match="country"):
        AdaptiveSearchInput(query="news", topic="news", country="china")

    with pytest.raises(ValidationError, match="language"):
        AdaptiveSearchInput(query="topic", filter_by_language=True)

    with pytest.raises(ValidationError, match="日期"):
        AdaptiveSearchInput(
            query="topic",
            start_date="2026-08-20",
            end_date="2026-08-01",
        )


@pytest.mark.anyio
async def test_transient_error_retries_once_but_authentication_does_not_retry() -> None:
    retrying_factory = RecordingSearchFactory(
        [TimeoutError("temporary"), result_payload()]
    )
    output = await adapter(retrying_factory).search(
        AdaptiveSearchInput(query="current topic")
    )
    assert output.results
    assert len(retrying_factory.init_calls) == 2

    auth_factory = RecordingSearchFactory(
        [ValueError("Error 401: invalid api key"), result_payload()]
    )
    with pytest.raises(TavilyAuthenticationError):
        await adapter(auth_factory).search(AdaptiveSearchInput(query="topic"))
    assert len(auth_factory.init_calls) == 1


@pytest.mark.anyio
async def test_timeout_is_normalized_after_single_retry() -> None:
    async def slow(_: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return result_payload()

    factory = RecordingSearchFactory([slow, slow])
    with pytest.raises(TavilyUnavailableError, match="超时"):
        await adapter(factory, timeout_seconds=0.001).search(
            AdaptiveSearchInput(query="topic")
        )
    assert len(factory.init_calls) == 2


@pytest.mark.anyio
async def test_unsafe_search_result_is_dropped_without_losing_safe_results() -> None:
    raw = result_payload()
    raw["results"] = [
        {
            "title": "不安全结果",
            "url": "https://unsafe.example/internal",
            "content": "不能进入研究上下文",
        },
        {
            "title": "安全结果",
            "url": "https://docs.example.com/current",
            "content": "可核验的公开资料",
        },
    ]

    async def reject_unsafe(value: str) -> str:
        if "unsafe.example" in value:
            raise InvalidSourceUrlError("网页地址必须指向公开站点")
        return value

    search = AdaptiveTavilySearch(
        tavily_api_key=SecretStr("secret-key"),
        tool_factory=RecordingSearchFactory([raw]),
        normalize_url=reject_unsafe,
        timeout_seconds=1,
        transient_retries=0,
    )

    output = await search.search(AdaptiveSearchInput(query="current topic"))

    assert [item.url for item in output.results] == [
        "https://docs.example.com/current"
    ]
