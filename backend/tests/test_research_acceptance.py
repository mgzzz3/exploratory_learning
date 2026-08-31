from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.schemas.learning_input import classify_learning_input
from app.schemas.research import ResearchBundle
from app.services.research_acceptance import (
    ResearchAcceptanceError,
    accept_research_bundle,
)


def source(
    source_id: str,
    *,
    title: str,
    url: str,
    method: str = "search",
) -> dict[str, Any]:
    from urllib.parse import urlsplit

    return {
        "id": source_id,
        "title": title,
        "url": url,
        "domain": urlsplit(url).hostname,
        "acquisition_method": method,
    }


def tool_call(*source_ids: str, name: str = "adaptive_tavily_search") -> dict[str, Any]:
    return {
        "call_id": "call_123456789",
        "tool_name": name,
        "parameter_kinds": ["query"],
        "response_source_ids": list(source_ids),
        "duration_ms": 10,
        "status": "success",
    }


def bundle(
    *,
    status: str = "ready",
    input_type: str = "keyword",
    interpretation: str | None = "AI agent 的环境、约束和反馈回路工程",
    sources: list[dict[str, Any]] | None = None,
    facts: list[dict[str, Any]] | None = None,
    alternatives: list[str] | None = None,
    original_url: str | None = None,
) -> ResearchBundle:
    selected_sources = sources
    if selected_sources is None:
        selected_sources = [
            source(
                "src_aaaaaaaaaaaa",
                title="Harness Engineering for AI agents",
                url="https://docs.example.com/harness",
            ),
            source(
                "src_bbbbbbbbbbbb",
                title="Agent feedback loop research",
                url="https://research.example.org/feedback",
            ),
        ]
    selected_facts = facts
    if selected_facts is None:
        selected_facts = [
            {
                "statement": "Harness Engineering 为 AI agent 设计环境、约束、工具和反馈回路。",
                "source_ids": [selected_sources[0]["id"]],
            },
            {
                "statement": "反馈回路让 agent 的行为可观察和可修正。",
                "source_ids": [selected_sources[-1]["id"]],
            },
            {
                "statement": "工程化约束使 agent 在可控边界内完成任务。",
                "source_ids": [selected_sources[0]["id"]],
            },
        ]
    payload: dict[str, Any] = {
        "input_type": input_type,
        "original_url": original_url,
        "status": status,
        "interpretation": interpretation,
        "retrieved_at": datetime.now(UTC),
        "sources": selected_sources,
        "facts": selected_facts,
        "tool_calls": (
            [
                tool_call(
                    *(item["id"] for item in selected_sources),
                    name=(
                        "adaptive_tavily_extract"
                        if input_type == "url"
                        else "adaptive_tavily_search"
                    ),
                )
            ]
            if selected_sources
            else []
        ),
        "alternatives": alternatives or [],
    }
    if status != "ready":
        payload["sources"] = selected_sources or []
        payload["facts"] = selected_facts or []
        payload["tool_calls"] = payload["tool_calls"] or [tool_call()]
    return ResearchBundle.model_validate(payload)


def test_ready_keyword_bundle_becomes_a_research_context() -> None:
    descriptor = classify_learning_input("Harness Engineering")

    context = accept_research_bundle(descriptor, bundle())

    assert context.input == descriptor
    assert len(context.sources) == 2
    assert len(context.facts) >= 3


@pytest.mark.parametrize("status", ["insufficient", "conflict"])
def test_insufficient_or_conflicting_evidence_fails_closed(status: str) -> None:
    descriptor = classify_learning_input("Harness Engineering")

    with pytest.raises(ResearchAcceptanceError) as captured:
        accept_research_bundle(descriptor, bundle(status=status))

    assert captured.value.code == "SOURCES_INSUFFICIENT"


def test_ambiguous_topic_returns_at_most_three_interpretations() -> None:
    descriptor = classify_learning_input("Mercury")
    research = bundle(
        status="ambiguous",
        interpretation=None,
        alternatives=["水星", "汞元素", "Mercury 软件"],
    )

    with pytest.raises(ResearchAcceptanceError) as captured:
        accept_research_bundle(descriptor, research)

    assert captured.value.code == "TOPIC_AMBIGUOUS"
    assert captured.value.details == {
        "interpretations": ["水星", "汞元素", "Mercury 软件"]
    }


def test_keyword_sources_must_be_independent() -> None:
    descriptor = classify_learning_input("Harness Engineering")
    same_domain = [
        source(
            "src_aaaaaaaaaaaa",
            title="Guide one",
            url="https://docs.example.com/one",
        ),
        source(
            "src_bbbbbbbbbbbb",
            title="Guide two",
            url="https://docs.example.com/two",
        ),
    ]

    with pytest.raises(ResearchAcceptanceError) as captured:
        accept_research_bundle(descriptor, bundle(sources=same_domain))

    assert captured.value.code == "SOURCES_INSUFFICIENT"
    assert captured.value.details["reason"] == "sources_not_independent"


def test_url_mode_accepts_the_original_page_as_the_only_source() -> None:
    page_url = "https://docs.example.com/article"
    descriptor = classify_learning_input(page_url)
    only_page = [
        source(
            "src_aaaaaaaaaaaa",
            title="A complete article",
            url=page_url,
            method="extract",
        )
    ]
    facts = [
        {
            "statement": f"Article fact {index}",
            "source_ids": ["src_aaaaaaaaaaaa"],
        }
        for index in range(1, 4)
    ]

    context = accept_research_bundle(
        descriptor,
        bundle(
            input_type="url",
            original_url=page_url,
            interpretation="基于用户提供文章的课程",
            sources=only_page,
            facts=facts,
        ),
    )

    assert len(context.sources) == 1
    assert context.sources[0].acquisition_method == "extract"


def test_harness_engineering_fixture_uses_current_ai_agent_meaning() -> None:
    descriptor = classify_learning_input("Harness Engineering")

    context = accept_research_bundle(descriptor, bundle())

    assert "AI agent" in context.interpretation
    assert "环境" in context.interpretation
    assert "反馈回路" in context.interpretation


def test_harness_engineering_wrong_field_is_rejected() -> None:
    descriptor = classify_learning_input("Harness Engineering")
    wrong = bundle(
        interpretation="Harness 公司的传统软件交付产品",
        facts=[
            {
                "statement": "Harness 是持续交付软件公司。",
                "source_ids": ["src_aaaaaaaaaaaa"],
            },
            {
                "statement": "该产品用于部署。",
                "source_ids": ["src_bbbbbbbbbbbb"],
            },
            {
                "statement": "该产品管理发布流水线。",
                "source_ids": ["src_aaaaaaaaaaaa"],
            },
        ],
    )

    with pytest.raises(ResearchAcceptanceError) as captured:
        accept_research_bundle(descriptor, wrong)

    assert captured.value.code == "SOURCES_INSUFFICIENT"
    assert captured.value.details["reason"] == "topic_interpretation_mismatch"
