from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.clients.ai import LocalContentGenerator
from app.schemas.game import GameCreateRequest
from app.schemas.learning_input import classify_learning_input
from app.services.generation_strategy import (
    GenerationResult,
    GroundedGenerationStrategy,
    LegacyGenerationStrategy,
    LocalResearcher,
    QuestionGenerationStrategy,
    UrlRequiresResearchError,
    build_generation_strategy,
)

from .fakes import FakeContentGenerator, generated_game


def grounded_result() -> GenerationResult:
    return GenerationResult.model_validate(
        {
            "game": generated_game("Harness Engineering"),
            "display_topic": "Harness Engineering",
            "input_type": "keyword",
            "source_input": "Harness Engineering",
            "retrieved_at": datetime.now(UTC),
            "sources": [
                {
                    "id": "src_aaaaaaaaaaaa",
                    "title": "Official guide",
                    "url": "https://docs.example.com/harness",
                    "domain": "docs.example.com",
                    "acquisition_method": "search",
                },
                {
                    "id": "src_bbbbbbbbbbbb",
                    "title": "Independent research",
                    "url": "https://research.example.org/harness",
                    "domain": "research.example.org",
                    "acquisition_method": "search",
                },
            ],
            "level_source_ids": [
                ["src_aaaaaaaaaaaa"],
                ["src_bbbbbbbbbbbb"],
                ["src_aaaaaaaaaaaa", "src_bbbbbbbbbbbb"],
            ],
        }
    )


class GroundedStub:
    async def generate(self, descriptor: Any) -> GenerationResult:
        del descriptor
        return grounded_result()


def test_client_cannot_override_server_generation_mode() -> None:
    with pytest.raises(ValidationError):
        GameCreateRequest.model_validate(
            {
                "topic": "Python 基础",
                "question_generation_mode": "legacy",
            }
        )


def test_both_strategies_share_one_generation_result_contract() -> None:
    grounded: QuestionGenerationStrategy = GroundedStub()
    legacy: QuestionGenerationStrategy = LegacyGenerationStrategy(
        FakeContentGenerator()
    )

    assert isinstance(grounded_result(), GenerationResult)
    assert hasattr(grounded, "generate")
    assert hasattr(legacy, "generate")


@pytest.mark.anyio
async def test_legacy_keyword_calls_original_generator_exactly_once() -> None:
    generator = FakeContentGenerator()
    strategy = LegacyGenerationStrategy(generator)

    result = await strategy.generate(classify_learning_input("Python 基础"))

    assert generator.calls == ["Python 基础"]
    assert result.game == generated_game("Python 基础")
    assert result.display_topic == "Python 基础"
    assert result.input_type == "keyword"
    assert result.source_input is None
    assert result.retrieved_at is None
    assert result.sources == []
    assert result.level_source_ids == [[], [], []]


@pytest.mark.anyio
async def test_legacy_url_fails_before_original_generator() -> None:
    generator = FakeContentGenerator()
    strategy = LegacyGenerationStrategy(generator)

    with pytest.raises(UrlRequiresResearchError) as captured:
        await strategy.generate(
            classify_learning_input("https://docs.example.com/current")
        )

    assert captured.value.code == "URL_REQUIRES_RESEARCH"
    assert generator.calls == []


def test_legacy_factory_never_constructs_grounded_strategy() -> None:
    grounded_calls: list[Settings] = []

    def grounded_factory(settings: Settings) -> QuestionGenerationStrategy:
        grounded_calls.append(settings)
        raise AssertionError("legacy must not construct grounded strategy")

    settings = Settings(
        _env_file=None,
        environment="test",
        question_generation_mode="legacy",
        use_mock_services=True,
    )
    strategy = build_generation_strategy(
        settings=settings,
        content_generator=FakeContentGenerator(),
        grounded_factory=grounded_factory,
    )

    assert isinstance(strategy, LegacyGenerationStrategy)
    assert grounded_calls == []


def test_grounded_factory_constructs_only_grounded_strategy() -> None:
    selected = GroundedStub()
    calls: list[Settings] = []

    def grounded_factory(settings: Settings) -> QuestionGenerationStrategy:
        calls.append(settings)
        return selected

    settings = Settings(
        _env_file=None,
        environment="test",
        question_generation_mode="grounded",
        use_mock_services=True,
    )
    legacy_generator = FakeContentGenerator()

    strategy = build_generation_strategy(
        settings=settings,
        content_generator=legacy_generator,
        grounded_factory=grounded_factory,
    )

    assert strategy is selected
    assert calls == [settings]
    assert legacy_generator.calls == []


@pytest.mark.parametrize(
    "patch",
    [
        {"input_type": "url"},
        {"retrieved_at": datetime.now(UTC)},
        {"level_source_ids": [["src_aaaaaaaaaaaa"], [], []]},
    ],
)
def test_legacy_result_cannot_claim_partial_grounding(patch: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "game": generated_game("Python 基础"),
        "display_topic": "Python 基础",
        "input_type": "keyword",
        "source_input": None,
        "retrieved_at": None,
        "sources": [],
        "level_source_ids": [[], [], []],
    }
    payload.update(patch)

    with pytest.raises(ValidationError):
        GenerationResult.model_validate(payload)


def test_grounded_result_rejects_unknown_or_missing_level_sources() -> None:
    payload = grounded_result().model_dump(mode="python")
    payload["level_source_ids"][0] = ["src_cccccccccccc"]

    with pytest.raises(ValidationError, match="来源"):
        GenerationResult.model_validate(payload)


@pytest.mark.anyio
async def test_grounded_url_uses_page_title_with_domain_fallback() -> None:
    async def keep_public_url(value: str) -> str:
        return value

    client = LocalContentGenerator()
    strategy = GroundedGenerationStrategy(
        researcher=LocalResearcher(),
        generator=client,
        validator=client,
        normalize_url=keep_public_url,
    )

    result = await strategy.generate(
        classify_learning_input("https://docs.example.com/current")
    )

    assert result.input_type == "url"
    assert result.display_topic == "docs.example.com"
    assert result.source_input == "https://docs.example.com/current"
    assert result.sources[0].title == "docs.example.com"
