from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.clients.tavily import AdaptiveSearchInput
from app.schemas.learning_input import classify_learning_input
from app.services.research_agent import ResearchAgent

from .test_research_agent import (
    ExtractStub,
    ScriptedAgentFactory,
    SearchStub,
    ready_bundle,
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("topic", "search_args"),
    [
        (
            "Python 元组",
            {
                "query": "Python 元组",
                "search_depth": "fast",
                "content_mode": "summary",
                "max_results": 3,
            },
        ),
        (
            "光合作用",
            {
                "query": "光合作用",
                "search_depth": "basic",
                "content_mode": "summary",
                "max_results": 5,
            },
        ),
        (
            "Harness Engineering 2026",
            {
                "query": "Harness Engineering AI agents 2026",
                "search_depth": "advanced",
                "content_mode": "summary",
                "max_results": 8,
                "language": "en",
                "filter_by_language": False,
            },
        ),
        (
            "一种新的专业知识",
            {
                "query": "一种新的专业知识 官方资料",
                "search_depth": "advanced",
                "content_mode": "full",
                "max_results": 3,
            },
        ),
        (
            "本周 AI 新闻",
            {
                "query": "本周 AI 新闻",
                "search_depth": "advanced",
                "content_mode": "summary",
                "max_results": 5,
                "topic": "news",
                "time_range": "week",
            },
        ),
        (
            "杭州低空经济政策",
            {
                "query": "杭州低空经济政策",
                "search_depth": "basic",
                "content_mode": "summary",
                "max_results": 5,
                "topic": "general",
                "country": "china",
                "language": "zh-cn",
                "filter_by_language": False,
            },
        ),
    ],
)
async def test_agent_search_parameter_choices_reach_the_guarded_adapter(
    topic: str,
    search_args: dict[str, Any],
) -> None:
    search = SearchStub()
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [("adaptive_tavily_search", search_args)],
                "response_builder": lambda outputs: ready_bundle("keyword", outputs),
            }
        ]
    )
    agent = ResearchAgent(
        model=object(),
        search=search,
        extract=ExtractStub(),
        agent_factory=factory,
        total_timeout_seconds=2,
    )

    await agent.research(classify_learning_input(topic))

    selected = search.calls[0]
    for name, value in search_args.items():
        assert getattr(selected, name) == value


@pytest.mark.anyio
async def test_agent_can_extract_after_summary_evidence_is_insufficient() -> None:
    search = SearchStub()
    extract = ExtractStub()
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [
                    (
                        "adaptive_tavily_search",
                        {
                            "query": "Harness Engineering",
                            "search_depth": "advanced",
                            "content_mode": "summary",
                            "max_results": 5,
                        },
                    ),
                    (
                        "adaptive_tavily_extract",
                        {
                            "urls": ["https://docs.example.com/harness-engineering"],
                            "extract_depth": "advanced",
                            "query": "environment constraints feedback loops",
                            "chunks_per_source": 3,
                        },
                    ),
                ],
                "response_builder": lambda outputs: ready_bundle("keyword", outputs),
            }
        ]
    )

    await ResearchAgent(
        model=object(),
        search=search,
        extract=extract,
        agent_factory=factory,
        total_timeout_seconds=2,
    ).research(classify_learning_input("Harness Engineering"))

    assert search.calls[0].content_mode == "summary"
    assert extract.calls[0].query == "environment constraints feedback loops"
    assert extract.calls[0].extract_depth == "advanced"


@pytest.mark.anyio
async def test_global_topic_can_add_english_search_without_country_filter() -> None:
    search = SearchStub()
    calls = [
        (
            "adaptive_tavily_search",
            {
                "query": "模型上下文协议",
                "max_results": 5,
                "language": "zh-cn",
                "filter_by_language": False,
            },
        ),
        (
            "adaptive_tavily_search",
            {
                "query": "Model Context Protocol official specification",
                "search_depth": "advanced",
                "max_results": 5,
                "language": "en",
                "filter_by_language": False,
            },
        ),
    ]
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": calls,
                "response_builder": lambda outputs: ready_bundle("keyword", outputs),
            }
        ]
    )

    await ResearchAgent(
        model=object(),
        search=search,
        extract=ExtractStub(),
        agent_factory=factory,
        total_timeout_seconds=2,
    ).research(classify_learning_input("模型上下文协议"))

    assert [item.country for item in search.calls] == [None, None]
    assert search.calls[1].query.startswith("Model Context Protocol")
    assert all(item.filter_by_language is False for item in search.calls)


def test_search_schema_has_no_fake_city_parameter_and_country_is_general_only() -> None:
    with pytest.raises(ValidationError):
        AdaptiveSearchInput.model_validate(
            {"query": "杭州天气", "city": "hangzhou", "max_results": 3}
        )
    with pytest.raises(ValidationError, match="country 只支持 general"):
        AdaptiveSearchInput(
            query="中国新闻",
            topic="news",
            country="china",
            max_results=3,
        )


@pytest.mark.anyio
async def test_system_guidance_contains_all_dynamic_decision_rules() -> None:
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [
                    (
                        "adaptive_tavily_search",
                        {"query": "Python 元组", "max_results": 3},
                    )
                ],
                "response_builder": lambda outputs: ready_bundle("keyword", outputs),
            }
        ]
    )
    await ResearchAgent(
        model=object(),
        search=SearchStub(),
        extract=ExtractStub(),
        agent_factory=factory,
        total_timeout_seconds=2,
    ).research(classify_learning_input("Python 元组"))

    prompt = factory.invocations[0]["system_prompt"]
    for rule in (
        "简单概念：basic/fast + summary + 3",
        "一般概念：basic + summary + 5",
        "新知识/复杂/多义：advanced + 5～8",
        "新闻：topic=news",
        "城市名必须保留在 query",
        "country 仅限 topic=general",
        "全球技术主题不得限制 country",
        "filter_by_language 默认 false",
        "最多 Search 2 次",
        "最多 Extract 2 次",
        "合计最多 4 次",
    ):
        assert rule in prompt
