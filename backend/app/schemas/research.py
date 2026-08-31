from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.game import GeneratedGame, GeneratedLevel
from app.schemas.learning_input import (
    InputDescriptor,
    InputType,
    classify_learning_input,
)


AcquisitionMethod = Literal["search", "extract"]
ResearchStatus = Literal["ready", "ambiguous", "insufficient", "conflict"]
ResearchToolName = Literal["adaptive_tavily_search", "adaptive_tavily_extract"]


GROUNDING_CHECK_FIELDS = (
    "title",
    *(
        field_path
        for level_position in range(3)
        for field_path in (
            f"levels[{level_position}].title",
            f"levels[{level_position}].intro",
            f"levels[{level_position}].question",
            f"levels[{level_position}].options[0]",
            f"levels[{level_position}].options[1]",
            f"levels[{level_position}].options[2]",
            f"levels[{level_position}].correct_option",
            f"levels[{level_position}].wrong_explanation",
            f"levels[{level_position}].praise",
            f"levels[{level_position}].takeaway",
        )
    ),
    "summary[0]",
    "summary[1]",
    "summary[2]",
)


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=8, max_length=2048)
    content: str = Field(min_length=1, max_length=40_000)
    score: float | None = Field(default=None, ge=0, le=1)
    published_date: datetime | None = None
    raw_content: str | None = Field(default=None, max_length=120_000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_url(value)


class ExtractedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=2048)
    title: str | None = Field(default=None, max_length=500)
    raw_content: str = Field(min_length=1, max_length=120_000)
    response_time: float | None = Field(default=None, ge=0)
    usage: dict[str, Any] | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_url(value)


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^src_[0-9a-f]{12}$")
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=8, max_length=2048)
    domain: str = Field(min_length=1, max_length=253)
    acquisition_method: AcquisitionMethod

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_url(value)

    @model_validator(mode="after")
    def validate_domain_matches_url(self) -> SourceReference:
        hostname = urlsplit(self.url).hostname
        if hostname is None or hostname.rstrip(".").lower() != self.domain.lower():
            raise ValueError("来源域名必须与 URL 一致")
        self.domain = self.domain.lower()
        return self


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=9, max_length=128)
    tool_name: ResearchToolName
    parameter_kinds: list[str] = Field(default_factory=list, max_length=20)
    response_source_ids: list[str] = Field(default_factory=list, max_length=8)
    duration_ms: int = Field(ge=0)
    status: Literal["success", "error"]

    @field_validator("parameter_kinds", "response_source_ids")
    @classmethod
    def validate_unique_items(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("工具轨迹列表不能重复")
        return value


class ResearchFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=2, max_length=1000)
    source_ids: list[str] = Field(min_length=1, max_length=5)

    @field_validator("source_ids")
    @classmethod
    def validate_unique_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("事实来源不能重复")
        return value


class ResearchConclusion(BaseModel):
    """Model-authored claims only; acquisition metadata belongs to the server."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: ResearchStatus
    interpretation: str | None = Field(default=None, max_length=500)
    source_ids: list[str] = Field(default_factory=list, max_length=5)
    facts: list[ResearchFact] = Field(default_factory=list, max_length=30)
    alternatives: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_conclusion(self) -> ResearchConclusion:
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("结论来源不能重复")
        if len(self.alternatives) != len(set(self.alternatives)):
            raise ValueError("候选解释不能重复")
        if self.status == "ready" and (
            not self.interpretation or not self.facts or not self.source_ids
        ):
            raise ValueError("可用结论必须包含解释、来源与事实")
        if any(
            not set(fact.source_ids).issubset(self.source_ids)
            for fact in self.facts
        ):
            raise ValueError("事实引用了未选择的来源")
        return self


class ResearchBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_type: InputType
    original_url: str | None = Field(default=None, max_length=2048)
    status: ResearchStatus
    interpretation: str | None = Field(default=None, max_length=500)
    retrieved_at: datetime
    sources: list[SourceReference] = Field(default_factory=list, max_length=5)
    facts: list[ResearchFact] = Field(default_factory=list, max_length=30)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list, max_length=4)
    alternatives: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_ready_evidence(self) -> ResearchBundle:
        if len(self.alternatives) != len(set(self.alternatives)):
            raise ValueError("候选解释不能重复")
        if self.status != "ready":
            return self
        if not self.interpretation:
            raise ValueError("可用研究结果必须包含主题解释")
        if not self.facts:
            raise ValueError("可用研究结果必须包含事实")
        if not self.tool_calls:
            raise ValueError("可用研究结果必须包含工具轨迹")
        if self.input_type == "keyword" and not 2 <= len(self.sources) <= 5:
            raise ValueError("关键词模式必须保留 2～5 条来源")
        if self.input_type == "url":
            if not 1 <= len(self.sources) <= 5:
                raise ValueError("URL 模式必须保留 1～5 条来源")
            if not self.original_url:
                raise ValueError("URL 模式必须记录原始页面")
            if self.original_url not in {item.url for item in self.sources}:
                raise ValueError("URL 模式来源必须包含原始页面")

        source_ids = [item.id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("来源 ID 不能重复")
        if len({item.url for item in self.sources}) != len(self.sources):
            raise ValueError("来源 URL 不能重复")
        known_ids = set(source_ids)
        referenced_ids = {
            source_id for fact in self.facts for source_id in fact.source_ids
        }
        referenced_ids.update(
            source_id
            for call in self.tool_calls
            for source_id in call.response_source_ids
        )
        if not referenced_ids.issubset(known_ids):
            raise ValueError("研究结果引用了不存在的来源 ID")
        return self


class ResearchContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: InputDescriptor
    interpretation: str = Field(min_length=1, max_length=500)
    retrieved_at: datetime
    sources: list[SourceReference] = Field(min_length=1, max_length=5)
    facts: list[ResearchFact] = Field(min_length=1, max_length=30)
    tool_calls: list[ToolCallRecord] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_evidence(self) -> ResearchContext:
        ResearchBundle(
            input_type=self.input.input_type,
            original_url=(
                self.input.normalized_input if self.input.input_type == "url" else None
            ),
            status="ready",
            interpretation=self.interpretation,
            retrieved_at=self.retrieved_at,
            sources=self.sources,
            facts=self.facts,
            tool_calls=self.tool_calls,
        )
        return self


class GroundedGeneratedLevel(GeneratedLevel):
    source_ids: list[str] = Field(min_length=1, max_length=5)

    @field_validator("source_ids")
    @classmethod
    def validate_unique_source_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("关卡来源不能重复")
        return value


class GroundedGeneratedGame(GeneratedGame):
    levels: list[GroundedGeneratedLevel] = Field(min_length=3, max_length=3)


class GroundingIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level_position: int | None = Field(default=None, ge=0, le=2)
    field: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=2, max_length=500)


class GroundingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    issues: list[GroundingIssue] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_pass_state(self) -> GroundingReport:
        if self.passed and self.issues:
            raise ValueError("通过校验时不能包含问题")
        if not self.passed and not self.issues:
            raise ValueError("未通过校验时必须说明问题")
        return self


def _validate_http_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError("来源 URL 无效") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("来源 URL 必须是 HTTP(S) 地址")
    return value
