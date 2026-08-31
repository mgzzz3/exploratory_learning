from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import app.schemas.research as schema
from app.clients.tavily import AdaptiveExtractInput, AdaptiveSearchInput
from app.schemas.learning_input import classify_learning_input
from app.services.research_acceptance import accept_research_bundle

from .test_research_models import source


NOW = datetime(2026, 8, 31, tzinfo=UTC)
SEARCH = "adaptive_tavily_search"
EXTRACT = "adaptive_tavily_extract"


def make_state(topic="高情商聊天"):
    from app.services.research_state import ResearchRunState

    return ResearchRunState(
        descriptor=classify_learning_input(topic), retrieved_at=NOW, clock=lambda: 12.0
    )


def conclusion(selected_sources, **overrides):
    return schema.ResearchConclusion.model_validate(
        {
            "status": "ready",
            "interpretation": "关于沟通的稳定主题",
            "source_ids": [item.id for item in selected_sources],
            "facts": [
                {"statement": f"资料支持的事实 {index}", "source_ids": [selected_sources[0].id]}
                for index in range(3)
            ],
            **overrides,
        }
    )


def record(state, sources, *, tool_name=SEARCH, params=None):
    if params is None:
        params = AdaptiveSearchInput(query="高情商聊天")
    return state.record_success(
        tool_name=tool_name,
        params=params,
        sources=sources,
        evidence=[{"source_id": item.id, "content": "bounded-evidence-marker"} for item in sources],
        started=11.875,
    )


@pytest.mark.parametrize("field,value", [
    ("retrieved_at", NOW.isoformat()), ("tool_calls", []),
    ("sources", []), ("original_url", "https://example.com"),
    ("raw_content", "raw-page-marker"),
])
def test_conclusion_rejects_model_supplied_server_metadata(field, value):
    with pytest.raises(ValidationError):
        conclusion([source(1), source(2)], **{field: value})


def test_backend_assembles_metadata_and_selected_evidence_without_raw_content():
    state = make_state()
    sources = [source(1), source(2), source(3)]
    actual = record(state, sources)
    selected = sources[:2]

    bundle = state.assemble(conclusion(selected))
    context = accept_research_bundle(state.descriptor, bundle)

    assert bundle.retrieved_at == NOW
    assert bundle.sources == selected
    assert bundle.tool_calls[0].call_id == actual.call_id
    assert actual.call_id.startswith("call_")
    assert bundle.tool_calls[0].duration_ms == 125
    assert bundle.tool_calls[0].response_source_ids == [item.id for item in selected]
    assert set(state.evidence) == {item.id for item in sources}
    assert "bounded-evidence-marker" not in bundle.model_dump_json()
    assert "bounded-evidence-marker" not in context.model_dump_json()
    assert bundle.input_type == "keyword"


@pytest.mark.parametrize("status", ["missing", "failed"])
def test_sources_from_missing_or_failed_tool_calls_cannot_be_evidence(status):
    state = make_state()
    if status == "failed":
        state.record_failure(SEARCH, AdaptiveSearchInput(query="test"), started=11.0)
    with pytest.raises(ValueError):
        state.assemble(conclusion([source(1), source(2)]))
    assert not state.evidence


def test_forged_sources_or_unselected_fact_references_are_rejected():
    state = make_state()
    record(state, [source(1), source(2)])
    with pytest.raises(ValueError):
        state.assemble(conclusion([source(1), source(3)]))
    with pytest.raises(ValidationError):
        conclusion([source(1), source(2)], facts=[{"statement": "伪造事实", "source_ids": [source(3).id]}])


def test_keyword_still_requires_two_sources_and_successful_search():
    state = make_state()
    record(state, [source(1)])
    with pytest.raises(ValueError):
        state.assemble(conclusion([source(1)]))
    extract_only = make_state()
    sources = [source(1, method="extract"), source(2, method="extract")]
    record(extract_only, sources, tool_name=EXTRACT, params=AdaptiveExtractInput(urls=[item.url for item in sources]))
    with pytest.raises(ValueError):
        extract_only.assemble(conclusion(sources))


def test_url_allows_one_original_extracted_source_and_keeps_server_url():
    original = source(1, method="extract")
    state = make_state(original.url)
    record(state, [original], tool_name=EXTRACT, params=AdaptiveExtractInput(urls=[original.url], full_page=True))
    bundle = state.assemble(conclusion([original]))
    assert bundle.original_url == original.url
    assert bundle.sources == [original]
    assert bundle.sources[0].acquisition_method == "extract"


@pytest.mark.parametrize("wrong", ["search", "replacement", "not_full_page"])
def test_url_rejects_search_or_replacement_or_partial_original_page(wrong):
    original = source(1, method="extract")
    state = make_state(original.url)
    chosen = [original] if wrong != "replacement" else [source(2, method="extract")]
    params = AdaptiveExtractInput(urls=[chosen[0].url], full_page=wrong != "not_full_page")
    if wrong == "search":
        record(state, chosen)
    else:
        record(state, chosen, tool_name=EXTRACT, params=params)
    with pytest.raises(ValueError):
        state.assemble(conclusion(chosen))


@pytest.mark.parametrize("status", ["ambiguous", "insufficient", "conflict"])
def test_nonready_conclusions_remain_business_results(status):
    state = make_state()
    record(state, [source(1), source(2)])
    result = state.assemble(schema.ResearchConclusion(status=status, alternatives=["解释一", "解释二"]))
    assert result.status == status
    assert result.alternatives == ["解释一", "解释二"]


def test_registered_metadata_is_a_snapshot_and_closed_state_cannot_be_reused():
    state = make_state()
    sources = [source(1), source(2)]
    record(state, sources)
    sources[0].title = "mutated-model-title"
    bundle = state.assemble(conclusion(sources))
    assert bundle.sources[0].title != "mutated-model-title"
    state.messages.append("message-marker")
    state.close()
    assert not state.calls and not state.evidence and not state.messages
    assert not state.observed_sources
    assert state.descriptor is None
    with pytest.raises(ValueError):
        state.assemble(conclusion(sources))


@pytest.mark.parametrize("count", [0, 6])
def test_ready_conclusion_rejects_empty_or_excessive_selected_sources(count):
    sources = [source(index + 1) for index in range(max(1, count))]
    with pytest.raises(ValidationError):
        conclusion(sources, source_ids=[item.id for item in sources[:count]])
