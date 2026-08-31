from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.clients.ai import (
    ContentGenerator,
    GroundedContentGenerator,
    GroundingValidator,
)
from app.core.config import Settings
from app.core.generation_budget import GenerationBudget
from app.core.observability import stage
from app.schemas.game import GeneratedGame, GenerationMode
from app.schemas.learning_input import InputDescriptor, InputType
from app.schemas.research import ResearchBundle, ResearchContext, SourceReference
from app.services.grounded_generation import generate_grounded_game
from app.services.research_acceptance import accept_research_bundle
from app.services.url_safety import normalize_public_url


UrlNormalizer = Callable[[str], Awaitable[str]]


class GenerationStrategyError(RuntimeError):
    code = "GENERATION_STRATEGY_FAILED"


class UrlRequiresResearchError(GenerationStrategyError):
    code = "URL_REQUIRES_RESEARCH"

    def __init__(self) -> None:
        super().__init__("当前服务模式暂不支持网页学习，请改用知识关键词")


class GenerationStrategyConfigurationError(GenerationStrategyError):
    pass


class GenerationResult(BaseModel):
    """Strategy-neutral data that can be persisted by one transaction."""

    model_config = ConfigDict(extra="forbid")

    game: GeneratedGame
    display_topic: str = Field(min_length=1, max_length=80)
    input_type: InputType
    source_input: str | None = Field(default=None, max_length=2048)
    retrieved_at: datetime | None = None
    sources: list[SourceReference] = Field(default_factory=list, max_length=5)
    level_source_ids: list[list[str]] = Field(min_length=3, max_length=3)
    generation_mode: GenerationMode = "legacy"
    verification_notice: str | None = None
    basic_fallback_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @model_validator(mode="before")
    @classmethod
    def compatible_mode(cls, value):
        # Compatibility for existing internal strategy producers. Never infer basic.
        if isinstance(value, dict) and "generation_mode" not in value:
            return {**value, "generation_mode": "grounded" if value.get("sources") else "legacy"}
        return value

    @model_validator(mode="after")
    def validate_grounding_state(self) -> GenerationResult:
        if self.generation_mode == "basic":
            if self.verification_notice != "未经联网核验" or self.basic_fallback_id is None or self.sources:
                raise ValueError("basic 必须包含未核验提示与许可 ID，且不能声明来源")
        elif self.verification_notice is not None or self.basic_fallback_id is not None:
            raise ValueError("只有 basic 可包含未核验提示与许可 ID")
        if (self.generation_mode == "grounded") != bool(self.sources):
            raise ValueError("生成模式与联网来源不一致")
        if not self.sources:
            if self.input_type != "keyword":
                raise ValueError("无联网来源的结果只能是关键词模式")
            if self.source_input is not None or self.retrieved_at is not None:
                raise ValueError("legacy 结果不能声明联网输入或检索时间")
            if any(self.level_source_ids):
                raise ValueError("legacy 关卡不能声明来源")
            return self

        if self.retrieved_at is None or not self.source_input:
            raise ValueError("grounded 结果必须包含来源输入和检索时间")
        if self.input_type == "keyword" and not 2 <= len(self.sources) <= 5:
            raise ValueError("grounded 关键词结果必须包含 2～5 条来源")
        if self.input_type == "url":
            if not 1 <= len(self.sources) <= 5:
                raise ValueError("grounded URL 结果必须包含 1～5 条来源")
            if self.source_input not in {source.url for source in self.sources}:
                raise ValueError("grounded URL 结果必须保留原始页面来源")

        known_ids = {source.id for source in self.sources}
        for source_ids in self.level_source_ids:
            if not source_ids:
                raise ValueError("grounded 每关必须关联来源")
            if len(source_ids) != len(set(source_ids)):
                raise ValueError("关卡来源不能重复")
            if not set(source_ids).issubset(known_ids):
                raise ValueError("关卡引用了不存在的来源")
        return self


class QuestionGenerationStrategy(Protocol):
    async def generate(self, descriptor: InputDescriptor) -> GenerationResult: ...


class Researcher(Protocol):
    async def research(self, descriptor: InputDescriptor) -> ResearchBundle: ...


ResearchAcceptor = Callable[[InputDescriptor, ResearchBundle], ResearchContext]


class GroundedGenerationStrategy:
    def __init__(
        self,
        *,
        researcher: Researcher,
        generator: GroundedContentGenerator,
        validator: GroundingValidator,
        accept_research: ResearchAcceptor = accept_research_bundle,
        normalize_url: UrlNormalizer = normalize_public_url,
        budget_factory: Callable[[], GenerationBudget] = GenerationBudget.start,
    ) -> None:
        self._researcher = researcher
        self._generator = generator
        self._validator = validator
        self._accept_research = accept_research
        self._normalize_url = normalize_url
        self._budget_factory = budget_factory

    async def generate(self, descriptor: InputDescriptor) -> GenerationResult:
        # The service invokes the selected strategy only after content safety.
        budget = self._budget_factory()
        async with budget.activate():
            return await self._generate(descriptor, budget)

    async def _generate(self, descriptor: InputDescriptor, budget: GenerationBudget) -> GenerationResult:
        async with budget.stage("research"):
            with stage("research"):
                prepared, context = await self._research(descriptor)
        game = await generate_grounded_game(
            context, generator=self._generator, validator=self._validator,
        )
        display_topic = prepared.display_topic
        if prepared.input_type == "url":
            original_page = next(source for source in context.sources if source.url == prepared.normalized_input)
            display_topic = (original_page.title or original_page.domain)[:80]
        return GenerationResult(
            game=game, display_topic=display_topic, input_type=prepared.input_type,
            source_input=prepared.normalized_input, retrieved_at=context.retrieved_at,
            sources=context.sources, level_source_ids=[level.source_ids for level in game.levels],
        )

    async def _research(self, descriptor: InputDescriptor):
        prepared = descriptor
        if descriptor.input_type == "url":
            normalized_url = await self._normalize_url(descriptor.normalized_input)
            prepared = descriptor.model_copy(
                update={
                    "normalized_input": normalized_url,
                    "display_topic": (urlsplit(normalized_url).hostname or "网页资料")[
                        :80
                    ],
                }
            )

        bundle = await self._researcher.research(prepared)
        context = self._accept_research(prepared, bundle)
        return prepared, context


class LocalResearcher:
    """Deterministic research fake for local/mock grounded development."""

    async def research(self, descriptor: InputDescriptor) -> ResearchBundle:
        if descriptor.input_type == "url":
            domain = urlsplit(descriptor.normalized_input).hostname or "example.com"
            sources = [
                {
                    "id": "src_aaaaaaaaaaaa",
                    "title": domain,
                    "url": descriptor.normalized_input,
                    "domain": domain,
                    "acquisition_method": "extract",
                }
            ]
            tool_name = "adaptive_tavily_extract"
        else:
            sources = [
                {
                    "id": "src_aaaaaaaaaaaa",
                    "title": "本地开发资料 A",
                    "url": "https://docs.example.com/topic",
                    "domain": "docs.example.com",
                    "acquisition_method": "search",
                },
                {
                    "id": "src_bbbbbbbbbbbb",
                    "title": "本地开发资料 B",
                    "url": "https://research.example.org/topic",
                    "domain": "research.example.org",
                    "acquisition_method": "search",
                },
            ]
            tool_name = "adaptive_tavily_search"
        source_ids = [str(source["id"]) for source in sources]
        interpretation = (
            "AI agent 的环境、约束、工具与反馈回路工程"
            if descriptor.normalized_input.casefold() == "harness engineering"
            else descriptor.display_topic
        )
        return ResearchBundle.model_validate(
            {
                "input_type": descriptor.input_type,
                "original_url": (
                    descriptor.normalized_input
                    if descriptor.input_type == "url"
                    else None
                ),
                "status": "ready",
                "interpretation": interpretation,
                "retrieved_at": datetime.now(UTC),
                "sources": sources,
                "facts": [
                    {
                        "statement": f"{interpretation} 包含需要先理解的核心概念。",
                        "source_ids": [source_ids[0]],
                    },
                    {
                        "statement": f"{interpretation} 需要结合适用条件理解。",
                        "source_ids": [source_ids[-1]],
                    },
                    {
                        "statement": f"{interpretation} 可以通过反馈检查理解结果。",
                        "source_ids": source_ids,
                    },
                ],
                "tool_calls": [
                    {
                        "call_id": "call_local_research",
                        "tool_name": tool_name,
                        "parameter_kinds": [
                            "urls" if descriptor.input_type == "url" else "query"
                        ],
                        "response_source_ids": source_ids,
                        "duration_ms": 0,
                        "status": "success",
                    }
                ],
                "alternatives": [],
            }
        )


class LegacyGenerationStrategy:
    def __init__(self, generator: ContentGenerator) -> None:
        self._generator = generator

    async def generate(self, descriptor: InputDescriptor) -> GenerationResult:
        if descriptor.input_type == "url":
            raise UrlRequiresResearchError()
        with stage("generation"):
            from app.core.observability import record_counts
            record_counts(model_calls=1)
            generated = await self._generator.generate(descriptor.normalized_input)
        return GenerationResult(
            game=generated,
            display_topic=descriptor.display_topic,
            input_type="keyword",
            source_input=None,
            retrieved_at=None,
            sources=[],
            level_source_ids=[[], [], []],
        )


GroundedStrategyFactory = Callable[[Settings], QuestionGenerationStrategy]


def build_generation_strategy(
    *,
    settings: Settings,
    content_generator: ContentGenerator,
    grounded_factory: GroundedStrategyFactory | None = None,
) -> QuestionGenerationStrategy:
    if settings.question_generation_mode == "legacy":
        return LegacyGenerationStrategy(content_generator)
    if grounded_factory is None:
        raise GenerationStrategyConfigurationError(
            "grounded 策略工厂尚未装配"
        )
    return grounded_factory(settings)
