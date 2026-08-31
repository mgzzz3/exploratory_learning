from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.clients.tavily import AdaptiveExtractInput, AdaptiveSearchInput, TavilyCallContext
from app.schemas.learning_input import InputDescriptor
from app.schemas.research import (
    ResearchBundle, ResearchConclusion, SourceReference, ToolCallRecord,
)
from app.services.page_content import PageContentWorkspace


SEARCH_TOOL_NAME = "adaptive_tavily_search"
EXTRACT_TOOL_NAME = "adaptive_tavily_extract"


class ResearchStateError(ValueError):
    def __init__(self, message: str, *, reason: str = "INVALID_RESEARCH_OUTPUT") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(repr=False)
class ActualToolCall:
    record: ToolCallRecord
    parameters: AdaptiveSearchInput | AdaptiveExtractInput
    available_source_ids: set[str]


@dataclass(repr=False)
class ResearchRunState:
    """A private, request-local ledger; never populated from model output."""

    descriptor: InputDescriptor | None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    clock: Callable[[], float] = time.monotonic
    calls: list[ActualToolCall] = field(default_factory=list)
    observed_sources: dict[str, list[SourceReference]] = field(default_factory=lambda: defaultdict(list))
    evidence: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    messages: list[Any] = field(default_factory=list)
    workspaces: list[PageContentWorkspace] = field(default_factory=list)
    closed: bool = False
    phase: str = "explore"
    corrections: int = 0
    execution: TavilyCallContext = field(default_factory=TavilyCallContext)

    def refresh_phase(self) -> None:
        if self.execution.remaining() == 0:
            self.phase = "finalize"

    def _require_open(self) -> InputDescriptor:
        if self.closed or self.descriptor is None:
            raise ValueError("研究请求状态已释放")
        return self.descriptor

    def record_success(
        self,
        *,
        tool_name: str,
        params: AdaptiveSearchInput | AdaptiveExtractInput,
        sources: list[SourceReference],
        evidence: list[dict[str, Any]],
        started: float,
    ) -> ToolCallRecord:
        self._require_open()
        source_ids = {source.id for source in sources}
        if {item.get("source_id") for item in evidence} != source_ids:
            raise ValueError("工具来源与证据块不一致")
        if any(not isinstance(item.get("content"), str) or not item["content"].strip() for item in evidence):
            raise ValueError("成功证据必须包含内容")
        record = self._make_record(tool_name, params, started, "success", sorted(source_ids))
        # Only commit the ledger once all result processing has succeeded.
        for source in sources:
            known = self.observed_sources[source.id]
            if source not in known:
                known.append(source.model_copy(deep=True))
        for item in evidence:
            if item["content"] not in self.evidence[item["source_id"]]:
                self.evidence[item["source_id"]].append(item["content"])
        self.calls.append(ActualToolCall(record, params.model_copy(deep=True), source_ids))
        return record.model_copy(deep=True)

    def record_failure(
        self, tool_name: str, params: AdaptiveSearchInput | AdaptiveExtractInput, *, started: float
    ) -> ToolCallRecord:
        self._require_open()
        record = self._make_record(tool_name, params, started, "error", [])
        self.calls.append(ActualToolCall(record, params.model_copy(deep=True), set()))
        return record.model_copy(deep=True)

    def _make_record(self, tool_name, params, started, status, source_ids) -> ToolCallRecord:
        return ToolCallRecord(
            call_id=f"call_{uuid.uuid4().hex}",
            tool_name=tool_name,
            parameter_kinds=sorted(params.model_dump(exclude_none=True)),
            response_source_ids=source_ids,
            duration_ms=max(0, round((self.clock() - started) * 1000)),
            status=status,
        )

    def assemble(self, conclusion: ResearchConclusion) -> ResearchBundle:
        descriptor = self._require_open()
        successful = [call for call in self.calls if call.record.status == "success"]
        if not successful:
            raise ResearchStateError("研究没有成功执行必需联网工具", reason="REQUIRED_TOOL_MISSING")
        if descriptor.input_type == "keyword":
            if not any(call.record.tool_name == SEARCH_TOOL_NAME for call in successful):
                raise ResearchStateError("关键词必须成功执行搜索", reason="REQUIRED_TOOL_MISSING")
        else:
            first = successful[0]
            if (
                first.record.tool_name != EXTRACT_TOOL_NAME
                or not isinstance(first.parameters, AdaptiveExtractInput)
                or first.parameters.urls != [descriptor.normalized_input]
                or not first.parameters.full_page
                or first.parameters.query is not None
            ):
                raise ValueError("URL 必须首先整页提取原始页面")
        acquired = set().union(*(call.available_source_ids for call in successful))
        selected = set(conclusion.source_ids)
        if not selected.issubset(acquired) or any(not self.evidence.get(item) for item in selected):
            raise ValueError("结论引用了未成功取得的来源")
        sources = []
        for source_id in conclusion.source_ids:
            variants = self.observed_sources[source_id]
            # Preserve original-page extraction when Search also returned that URL.
            chosen = next((source for source in variants if source.acquisition_method == "extract"), variants[0])
            sources.append(chosen.model_copy(deep=True))
        if descriptor.input_type == "url" and conclusion.status == "ready":
            if not any(source.url == descriptor.normalized_input and source.acquisition_method == "extract" for source in sources):
                raise ValueError("URL 结论必须保留原始页面提取来源")
        calls = [
            call.record.model_copy(deep=True, update={
                "response_source_ids": [item for item in call.record.response_source_ids if item in selected]
            })
            for call in self.calls
        ]
        return ResearchBundle(
            input_type=descriptor.input_type,
            original_url=descriptor.normalized_input if descriptor.input_type == "url" else None,
            status=conclusion.status,
            interpretation=conclusion.interpretation,
            retrieved_at=self.retrieved_at,
            sources=sources,
            facts=[fact.model_copy(deep=True) for fact in conclusion.facts],
            tool_calls=calls,
            alternatives=list(conclusion.alternatives),
        )

    def close(self) -> None:
        for workspace in self.workspaces:
            workspace.close()
        self.workspaces.clear()
        self.calls.clear()
        self.observed_sources.clear()
        self.evidence.clear()
        self.messages.clear()
        self.descriptor = None
        self.closed = True
