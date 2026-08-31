from __future__ import annotations

from typing import Any

from app.schemas.learning_input import InputDescriptor
from app.schemas.research import ResearchBundle, ResearchContext


class ResearchAcceptanceError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def accept_research_bundle(
    descriptor: InputDescriptor,
    bundle: ResearchBundle,
) -> ResearchContext:
    if bundle.input_type != descriptor.input_type:
        raise _insufficient("input_type_mismatch")

    if bundle.status == "ambiguous":
        raise ResearchAcceptanceError(
            code="TOPIC_AMBIGUOUS",
            message="这个主题可能有多种意思，请选择或补充说明",
            details={"interpretations": bundle.alternatives[:3]},
        )
    if bundle.status in {"insufficient", "conflict"}:
        reason = (
            "sources_conflict"
            if bundle.status == "conflict"
            else "sources_insufficient"
        )
        raise _insufficient(reason)
    if bundle.status != "ready":
        raise _insufficient("unknown_research_status")

    if len(bundle.facts) < 3:
        raise _insufficient("fewer_than_three_supported_facts")

    if descriptor.input_type == "keyword":
        if not 2 <= len(bundle.sources) <= 5:
            raise _insufficient("keyword_source_count")
        independent_domains = {source.domain.casefold() for source in bundle.sources}
        if len(independent_domains) < 2:
            raise _insufficient("sources_not_independent")
    else:
        if not 1 <= len(bundle.sources) <= 5:
            raise _insufficient("url_source_count")
        original = next(
            (
                source
                for source in bundle.sources
                if source.url == descriptor.normalized_input
            ),
            None,
        )
        if original is None or original.acquisition_method != "extract":
            raise _insufficient("original_page_missing")

    if _is_harness_engineering(descriptor) and not _is_current_harness_meaning(bundle):
        raise _insufficient("topic_interpretation_mismatch")

    assert bundle.interpretation is not None
    return ResearchContext(
        input=descriptor,
        interpretation=bundle.interpretation,
        retrieved_at=bundle.retrieved_at,
        sources=bundle.sources,
        facts=bundle.facts,
        tool_calls=bundle.tool_calls,
    )


def _insufficient(reason: str) -> ResearchAcceptanceError:
    return ResearchAcceptanceError(
        code="SOURCES_INSUFFICIENT",
        message="联网资料不足以可靠生成三关，请换个更具体的主题",
        details={"reason": reason},
    )


def _is_harness_engineering(descriptor: InputDescriptor) -> bool:
    return descriptor.normalized_input.casefold() == "harness engineering"


def _is_current_harness_meaning(bundle: ResearchBundle) -> bool:
    combined = "\n".join(
        [
            bundle.interpretation or "",
            *(fact.statement for fact in bundle.facts),
            *(source.title for source in bundle.sources),
        ]
    ).casefold()
    semantic_groups = (
        ("ai agent", "agentic", "智能体"),
        ("环境", "environment"),
        ("约束", "constraint"),
        ("反馈回路", "feedback loop"),
    )
    return all(any(term in combined for term in group) for group in semantic_groups)
