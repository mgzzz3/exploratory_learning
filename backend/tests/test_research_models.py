from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from app.schemas.research import (
    ExtractedPage,
    GroundedGeneratedGame,
    GroundingIssue,
    GroundingReport,
    InputDescriptor,
    ResearchBundle,
    ResearchContext,
    ResearchFact,
    SearchResult,
    SourceReference,
    ToolCallRecord,
)

from .fakes import generated_game


NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def source(
    index: int,
    *,
    method: str = "search",
    url: str | None = None,
) -> SourceReference:
    resolved_url = url or f"https://example{index}.com/article"
    return SourceReference(
        id=f"src_{index:012x}",
        title=f"来源 {index}",
        url=resolved_url,
        domain=urlsplit(resolved_url).hostname or "invalid",
        acquisition_method=method,
    )


def tool_call(*source_ids: str, tool: str = "adaptive_tavily_search") -> ToolCallRecord:
    return ToolCallRecord(
        call_id="call_123456789",
        tool_name=tool,
        parameter_kinds=["query", "search_depth"],
        response_source_ids=list(source_ids),
        duration_ms=42,
        status="success",
    )


def fact(*source_ids: str) -> ResearchFact:
    return ResearchFact(statement="可核验的知识事实", source_ids=list(source_ids))


def test_provider_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SearchResult(
            title="标题",
            url="https://example.com",
            content="摘要",
            score=0.9,
            unexpected=True,
        )

    with pytest.raises(ValidationError):
        ExtractedPage(
            url="https://example.com",
            raw_content="正文",
            unexpected=True,
        )


def test_source_reference_requires_stable_id_http_url_and_method() -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            id="unstable",
            title="来源",
            url="file:///tmp/a",
            domain="example.com",
            acquisition_method="crawl",
        )


def test_ready_keyword_bundle_requires_two_to_five_sources() -> None:
    first = source(1)
    with pytest.raises(ValidationError, match="2～5"):
        ResearchBundle(
            input_type="keyword",
            status="ready",
            interpretation="Harness Engineering（AI Agent 工程）",
            retrieved_at=NOW,
            sources=[first],
            facts=[fact(first.id)],
            tool_calls=[tool_call(first.id)],
        )

    second = source(2)
    bundle = ResearchBundle(
        input_type="keyword",
        status="ready",
        interpretation="Harness Engineering（AI Agent 工程）",
        retrieved_at=NOW,
        sources=[first, second],
        facts=[fact(first.id, second.id)],
        tool_calls=[tool_call(first.id, second.id)],
    )
    assert len(bundle.sources) == 2


def test_ready_url_bundle_allows_one_source_but_must_keep_original_page() -> None:
    original_url = "https://example.com/guide"
    original = source(1, method="extract", url=original_url)
    bundle = ResearchBundle(
        input_type="url",
        original_url=original_url,
        status="ready",
        interpretation="指定页面",
        retrieved_at=NOW,
        sources=[original],
        facts=[fact(original.id)],
        tool_calls=[tool_call(original.id, tool="adaptive_tavily_extract")],
    )
    assert bundle.sources == [original]

    with pytest.raises(ValidationError, match="原始页面"):
        ResearchBundle(
            input_type="url",
            original_url=original_url,
            status="ready",
            interpretation="错误替代页面",
            retrieved_at=NOW,
            sources=[source(2, method="extract")],
            facts=[fact("src_000000000002")],
            tool_calls=[
                tool_call("src_000000000002", tool="adaptive_tavily_extract")
            ],
        )


def test_bundle_rejects_unknown_source_references() -> None:
    sources = [source(1), source(2)]
    with pytest.raises(ValidationError, match="不存在"):
        ResearchBundle(
            input_type="keyword",
            status="ready",
            interpretation="主题",
            retrieved_at=NOW,
            sources=sources,
            facts=[fact("src_ffffffffffff")],
            tool_calls=[tool_call(*(item.id for item in sources))],
        )


def test_grounded_game_requires_non_empty_source_ids_and_keeps_game_rules() -> None:
    payload = generated_game("Harness Engineering").model_dump()
    for level in payload["levels"]:
        level["source_ids"] = ["src_000000000001"]

    game = GroundedGeneratedGame.model_validate(payload)
    assert all(level.source_ids for level in game.levels)

    payload["levels"][0]["source_ids"] = []
    with pytest.raises(ValidationError):
        GroundedGeneratedGame.model_validate(payload)


def test_research_context_requires_mode_matched_ready_evidence() -> None:
    sources = [source(1), source(2)]
    context = ResearchContext(
        input=InputDescriptor(
            input_type="keyword",
            original_input="Harness Engineering",
            normalized_input="Harness Engineering",
            display_topic="Harness Engineering",
        ),
        interpretation="AI Agent 的 Harness Engineering",
        retrieved_at=NOW,
        sources=sources,
        facts=[fact(*(item.id for item in sources))],
        tool_calls=[tool_call(*(item.id for item in sources))],
    )
    assert context.input.input_type == "keyword"


def test_grounding_report_pass_and_issue_states_are_consistent() -> None:
    assert GroundingReport(passed=True, issues=[]).passed is True

    with pytest.raises(ValidationError):
        GroundingReport(
            passed=True,
            issues=[
                GroundingIssue(
                    level_position=0,
                    field="question",
                    message="证据不支持",
                )
            ],
        )

    with pytest.raises(ValidationError):
        GroundingReport(passed=False, issues=[])
