from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from app.clients.tavily import (
    AdaptiveExtractOutput,
    AdaptiveSearchOutput,
)
from app.schemas.learning_input import classify_learning_input
from app.schemas.research import ExtractedPage, ResearchBundle, ResearchConclusion, SearchResult
from app.services.research_agent import (
    ResearchAgent,
    ResearchAgentFailedError,
    _parse_structured_response,
)


PUBLIC_URL = "https://docs.example.com/harness-engineering"
OTHER_URL = "https://research.example.org/current-guide"


@dataclass
class SearchStub:
    calls: list[Any] = field(default_factory=list)

    async def search(self, params: Any, **kwargs) -> AdaptiveSearchOutput:
        self.calls.append(params)
        return AdaptiveSearchOutput(
            results=[
                SearchResult(
                    title="Harness Engineering",
                    url=PUBLIC_URL,
                    content="Harness engineering designs agent environments and feedback loops.",
                    score=0.99,
                ),
                SearchResult(
                    title="Agent harness guide",
                    url=OTHER_URL,
                    content="A current guide to constraints, tools, and evaluation feedback.",
                    score=0.95,
                ),
            ]
        )


class SlowSearchStub(SearchStub):
    async def search(self, params: Any, **kwargs) -> AdaptiveSearchOutput:
        await asyncio.sleep(0.05)
        return await super().search(params)


@dataclass
class ExtractStub:
    calls: list[Any] = field(default_factory=list)

    async def extract(self, params: Any, **kwargs) -> AdaptiveExtractOutput:
        self.calls.append(params)
        return AdaptiveExtractOutput(
            pages=[
                ExtractedPage(
                    url=url,
                    title="Harness Engineering page",
                    raw_content=(
                        "# Harness Engineering\n\n"
                        "The practice engineers an AI agent's environment, constraints, "
                        "tools, and feedback loops."
                    ),
                )
                for url in params.urls
            ]
        )


class ScriptedCompiledAgent:
    def __init__(
        self,
        *,
        tools: list[Any],
        scripts: list[dict[str, Any]],
        middleware: list[Any],
    ) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.scripts = scripts
        self.outputs: list[dict[str, Any]] = []
        self.middleware = middleware

    async def ainvoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        script = self.scripts.pop(0)
        for _ in range(script.get("model_calls", 1)):
            for item in self.middleware:
                await item.abefore_model(payload, None)
        for tool_name, args in script.get("calls", []):
            if tool_name not in self.tools:
                raise ResearchAgentFailedError("Agent 尝试调用白名单外工具")
            output = await self.tools[tool_name].ainvoke(args)
            if output.get("status") != "blocked":
                self.outputs.append(output)
        return {"structured_response": script["response_builder"](self.outputs), "messages": payload["messages"]}


@dataclass
class ScriptedAgentFactory:
    scripts: list[dict[str, Any]]
    invocations: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, **kwargs: Any) -> ScriptedCompiledAgent:
        self.invocations.append(kwargs)
        assert {tool.name for tool in kwargs["tools"]} == {
            "adaptive_tavily_search",
            "adaptive_tavily_extract",
        }
        assert kwargs["response_format"].schema is ResearchConclusion
        return ScriptedCompiledAgent(
            tools=kwargs["tools"],
            scripts=self.scripts,
            middleware=kwargs["middleware"],
        )


def ready_bundle(
    input_type: str,
    outputs: list[dict[str, Any]],
    *,
    original_url: str | None = None,
) -> ResearchConclusion:
    sources_by_id: dict[str, dict[str, Any]] = {}
    for output in outputs:
        for source in output["sources"]:
            previous = sources_by_id.get(source["id"])
            if previous is None or source["acquisition_method"] == "extract":
                sources_by_id[source["id"]] = source
    selected_sources = list(sources_by_id.values())[:5]
    return ResearchConclusion.model_validate(
        {
            "status": "ready",
            "interpretation": "AI agent 的环境、约束、工具与反馈回路工程",
            "source_ids": [source["id"] for source in selected_sources],
            "facts": [
                {
                    "statement": "Harness Engineering 包含环境与反馈回路设计。",
                    "source_ids": [selected_sources[0]["id"]],
                }
            ],
        }
    )


def test_plain_json_final_message_is_rejected_even_if_legacy_bundle_is_valid() -> None:
    expected = ResearchBundle.model_validate(
        {
            "input_type": "keyword",
            "status": "ready",
            "interpretation": "可核验主题",
            "retrieved_at": datetime.now(UTC),
            "sources": [
                {
                    "id": "src_aaaaaaaaaaaa",
                    "title": "公开资料",
                    "url": PUBLIC_URL,
                    "domain": "docs.example.com",
                    "acquisition_method": "search",
                },
                {
                    "id": "src_bbbbbbbbbbbb",
                    "title": "独立公开资料",
                    "url": OTHER_URL,
                    "domain": "research.example.org",
                    "acquisition_method": "search",
                },
            ],
            "facts": [
                {
                    "statement": "这是公开资料支持的事实。",
                    "source_ids": ["src_aaaaaaaaaaaa"],
                }
            ],
            "tool_calls": [
                {
                    "call_id": "call_public_search",
                    "tool_name": "adaptive_tavily_search",
                    "parameter_kinds": ["query"],
                    "response_source_ids": [
                        "src_aaaaaaaaaaaa",
                        "src_bbbbbbbbbbbb",
                    ],
                    "duration_ms": 1,
                    "status": "success",
                }
            ],
        }
    )

    for content in (expected.model_dump_json(), f"```json\n{expected.model_dump_json()}\n```"):
        with pytest.raises(ResearchAgentFailedError, match="结构化"):
            _parse_structured_response({"messages": [AIMessage(content=content)]})


def make_agent(factory: ScriptedAgentFactory, **overrides: Any) -> ResearchAgent:
    return ResearchAgent(
        model=object(),
        search=SearchStub(),
        extract=ExtractStub(),
        agent_factory=factory,
        total_timeout_seconds=2,
        **overrides,
    )


@pytest.mark.anyio
async def test_keyword_requires_search_and_can_stop_after_one_tool() -> None:
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [
                    (
                        "adaptive_tavily_search",
                        {"query": "Harness Engineering", "max_results": 3},
                    )
                ],
                "response_builder": lambda outputs: ready_bundle("keyword", outputs),
            }
        ]
    )
    agent = make_agent(factory)

    result = await agent.research(classify_learning_input("Harness Engineering"))

    assert result.status == "ready"
    assert [call.tool_name for call in result.tool_calls] == [
        "adaptive_tavily_search"
    ]


@pytest.mark.anyio
async def test_url_must_extract_exact_original_page_first() -> None:
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [
                    (
                        "adaptive_tavily_extract",
                        {
                            "urls": [PUBLIC_URL],
                            "extract_depth": "basic",
                            "full_page": True,
                        },
                    )
                ],
                "response_builder": lambda outputs: ready_bundle(
                    "url", outputs, original_url=PUBLIC_URL
                ),
            }
        ]
    )

    result = await make_agent(factory).research(classify_learning_input(PUBLIC_URL))

    assert result.original_url == PUBLIC_URL
    assert result.sources[0].url == PUBLIC_URL


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("topic", "calls", "expected_order"),
    [
        (
            "Harness Engineering",
            [
                (
                    "adaptive_tavily_search",
                    {"query": "Harness Engineering", "max_results": 3},
                ),
                (
                    "adaptive_tavily_extract",
                    {
                        "urls": [PUBLIC_URL],
                        "extract_depth": "advanced",
                        "query": "feedback loops",
                    },
                ),
            ],
            ["adaptive_tavily_search", "adaptive_tavily_extract"],
        ),
        (
            PUBLIC_URL,
            [
                (
                    "adaptive_tavily_extract",
                    {
                        "urls": [PUBLIC_URL],
                        "extract_depth": "basic",
                        "full_page": True,
                    },
                ),
                (
                    "adaptive_tavily_search",
                    {"query": "Harness Engineering verification", "max_results": 3},
                ),
            ],
            ["adaptive_tavily_extract", "adaptive_tavily_search"],
        ),
    ],
)
async def test_agent_can_choose_search_extract_in_either_valid_order(
    topic: str,
    calls: list[tuple[str, dict[str, Any]]],
    expected_order: list[str],
) -> None:
    descriptor = classify_learning_input(topic)
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": calls,
                "response_builder": lambda outputs: ready_bundle(
                    descriptor.input_type,
                    outputs,
                    original_url=(
                        descriptor.normalized_input
                        if descriptor.input_type == "url"
                        else None
                    ),
                ),
            }
        ]
    )

    result = await make_agent(factory).research(descriptor)

    assert [call.tool_name for call in result.tool_calls] == expected_order


@pytest.mark.anyio
async def test_zero_tool_result_gets_one_controlled_retry_then_fails() -> None:
    direct_answer = lambda _: {"status": "insufficient"}
    factory = ScriptedAgentFactory(
        scripts=[
            {"response_builder": direct_answer},
            {"response_builder": direct_answer},
        ]
    )

    with pytest.raises(ResearchAgentFailedError) as caught:
        await make_agent(factory).research(classify_learning_input("new concept"))

    assert caught.value.reason == "REQUIRED_TOOL_MISSING"
    assert len(factory.invocations) == 1


@pytest.mark.anyio
async def test_url_cannot_search_before_extracting_original_page() -> None:
    invalid_script = {
        "calls": [
            (
                "adaptive_tavily_search",
                {"query": "replacement page", "max_results": 3},
            )
        ],
        "response_builder": lambda outputs: ready_bundle(
            "url", outputs, original_url=PUBLIC_URL
        ),
    }
    factory = ScriptedAgentFactory(scripts=[invalid_script, invalid_script])

    with pytest.raises(ResearchAgentFailedError, match="原始页面"):
        await make_agent(factory).research(classify_learning_input(PUBLIC_URL))


@pytest.mark.anyio
async def test_forged_tool_trace_is_rejected_after_retry() -> None:
    def forged(outputs: list[dict[str, Any]]) -> dict[str, Any]:
        result = ready_bundle("keyword", outputs).model_dump()
        result["tool_calls"] = [{"call_id": "call_forged"}]
        return result

    script = {
        "calls": [
            (
                "adaptive_tavily_search",
                {"query": "Harness Engineering", "max_results": 3},
            )
        ],
        "response_builder": forged,
    }
    factory = ScriptedAgentFactory(scripts=[script, script])

    with pytest.raises(ResearchAgentFailedError, match="结构化"):
        await make_agent(factory).research(
            classify_learning_input("Harness Engineering")
        )


@pytest.mark.anyio
async def test_invalid_structured_output_is_rejected_after_retry() -> None:
    factory = ScriptedAgentFactory(
        scripts=[
            {"response_builder": lambda _: {"unexpected": True}},
            {"response_builder": lambda _: {"unexpected": True}},
        ]
    )

    with pytest.raises(ResearchAgentFailedError, match="结构化"):
        await make_agent(factory).research(classify_learning_input("new concept"))


@pytest.mark.anyio
async def test_tool_limit_converges_but_model_budget_fails_closed() -> None:
    search_call = (
        "adaptive_tavily_search",
        {"query": "Harness Engineering", "max_results": 3},
    )
    too_many_tools = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [search_call] * 5,
                "response_builder": lambda outputs: ready_bundle("keyword", outputs),
            }
        ]
    )
    result = await make_agent(too_many_tools).research(classify_learning_input("Harness Engineering"))
    assert result.status == "ready"
    assert len(result.tool_calls) == 2

    too_many_models = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [search_call],
                "model_calls": 7,
                "response_builder": lambda outputs: ready_bundle("keyword", outputs),
            }
        ]
    )
    with pytest.raises(ResearchAgentFailedError, match="模型调用预算"):
        await make_agent(too_many_models).research(
            classify_learning_input("Harness Engineering")
        )


@pytest.mark.anyio
async def test_agent_receives_only_whitelisted_tools() -> None:
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [("shell", {"command": "env"})],
                "response_builder": lambda _: {},
            }
        ]
    )

    with pytest.raises(ResearchAgentFailedError, match="白名单"):
        await make_agent(factory).research(classify_learning_input("new concept"))


@pytest.mark.anyio
async def test_total_time_budget_fails_closed() -> None:
    factory = ScriptedAgentFactory(
        scripts=[
            {
                "calls": [
                    (
                        "adaptive_tavily_search",
                        {"query": "Harness Engineering", "max_results": 3},
                    )
                ],
                "response_builder": lambda outputs: ready_bundle("keyword", outputs),
            }
        ]
    )
    agent = ResearchAgent(
        model=object(),
        search=SlowSearchStub(),
        extract=ExtractStub(),
        agent_factory=factory,
        total_timeout_seconds=0.01,
    )

    with pytest.raises(ResearchAgentFailedError, match="总预算"):
        await agent.research(classify_learning_input("Harness Engineering"))
