from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.clients.ai import DeepSeekContentGenerator
from app.schemas.learning_input import classify_learning_input
from app.schemas.research import (
    GROUNDING_CHECK_FIELDS,
    GroundedGeneratedGame,
    GroundingIssue,
    GroundingReport,
    ResearchContext,
)
from app.services.grounded_generation import (
    GroundingValidationError,
    generate_grounded_game,
)

from .fakes import generated_game


def research_context() -> ResearchContext:
    return ResearchContext.model_validate(
        {
            "input": classify_learning_input("Harness Engineering"),
            "interpretation": "AI agent 的环境、约束、工具与反馈回路工程",
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
                    "url": "https://research.example.org/feedback",
                    "domain": "research.example.org",
                    "acquisition_method": "search",
                },
            ],
            "facts": [
                {
                    "statement": "Harness Engineering 设计 agent 的运行环境。",
                    "source_ids": ["src_aaaaaaaaaaaa"],
                },
                {
                    "statement": "约束和工具让 agent 在边界内行动。",
                    "source_ids": ["src_aaaaaaaaaaaa"],
                },
                {
                    "statement": "反馈回路用于观察并修正 agent 行为。",
                    "source_ids": ["src_bbbbbbbbbbbb"],
                },
            ],
            "tool_calls": [
                {
                    "call_id": "call_123456789",
                    "tool_name": "adaptive_tavily_search",
                    "parameter_kinds": ["query"],
                    "response_source_ids": [
                        "src_aaaaaaaaaaaa",
                        "src_bbbbbbbbbbbb",
                    ],
                    "duration_ms": 20,
                    "status": "success",
                }
            ],
        }
    )


def grounded_game(*, source_ids: list[list[str]] | None = None) -> GroundedGeneratedGame:
    payload = generated_game("Harness Engineering").model_dump(mode="python")
    selected = source_ids or [
        ["src_aaaaaaaaaaaa"],
        ["src_aaaaaaaaaaaa"],
        ["src_aaaaaaaaaaaa", "src_bbbbbbbbbbbb"],
    ]
    for level, ids in zip(payload["levels"], selected, strict=True):
        level["source_ids"] = ids
    return GroundedGeneratedGame.model_validate(payload)


@dataclass
class DraftGeneratorStub:
    drafts: list[GroundedGeneratedGame]
    feedback_calls: list[list[GroundingIssue]] = field(default_factory=list)

    async def generate_grounded(
        self,
        context: ResearchContext,
        issues: list[GroundingIssue],
    ) -> GroundedGeneratedGame:
        del context
        self.feedback_calls.append(issues)
        return self.drafts.pop(0)


@dataclass
class ValidatorStub:
    reports: list[GroundingReport]
    calls: list[GroundedGeneratedGame] = field(default_factory=list)

    async def validate_grounding(
        self,
        context: ResearchContext,
        game: GroundedGeneratedGame,
    ) -> GroundingReport:
        del context
        self.calls.append(game)
        return self.reports.pop(0)


PASS = GroundingReport(passed=True, issues=[])
UNSUPPORTED_INTRO = GroundingReport(
    passed=False,
    issues=[
        GroundingIssue(
            level_position=0,
            field="levels[0].intro",
            message="介绍包含证据没有支持的新结论",
        )
    ],
)


@pytest.mark.anyio
async def test_grounded_game_passes_with_real_level_sources() -> None:
    generator = DraftGeneratorStub([grounded_game()])
    validator = ValidatorStub([PASS])

    result = await generate_grounded_game(
        research_context(),
        generator=generator,
        validator=validator,
    )

    assert result == grounded_game()
    assert generator.feedback_calls == [[]]
    assert validator.calls == [result]


@pytest.mark.anyio
async def test_unknown_level_source_is_feedback_not_sent_to_model_validator() -> None:
    bad = grounded_game(
        source_ids=[
            ["src_cccccccccccc"],
            ["src_aaaaaaaaaaaa"],
            ["src_bbbbbbbbbbbb"],
        ]
    )
    corrected = grounded_game()
    generator = DraftGeneratorStub([bad, corrected])
    validator = ValidatorStub([PASS])

    result = await generate_grounded_game(
        research_context(),
        generator=generator,
        validator=validator,
    )

    assert result == corrected
    assert validator.calls == [corrected]
    assert generator.feedback_calls[1][0].field == "levels[0].source_ids"


@pytest.mark.anyio
async def test_validator_feedback_causes_exactly_one_regeneration() -> None:
    first = grounded_game()
    second = grounded_game()
    second.levels[0].intro = "修正后的、有证据支持的介绍文字。"
    generator = DraftGeneratorStub([first, second])
    validator = ValidatorStub([UNSUPPORTED_INTRO, PASS])

    result = await generate_grounded_game(
        research_context(),
        generator=generator,
        validator=validator,
    )

    assert result == second
    assert len(generator.feedback_calls) == 2
    assert generator.feedback_calls[0] == []
    assert generator.feedback_calls[1] == UNSUPPORTED_INTRO.issues
    assert len(validator.calls) == 2


@pytest.mark.anyio
async def test_second_grounding_failure_returns_stable_error() -> None:
    generator = DraftGeneratorStub([grounded_game(), grounded_game()])
    validator = ValidatorStub([UNSUPPORTED_INTRO, UNSUPPORTED_INTRO])

    with pytest.raises(GroundingValidationError) as captured:
        await generate_grounded_game(
            research_context(),
            generator=generator,
            validator=validator,
        )

    assert captured.value.code == "GROUNDING_VALIDATION_FAILED"
    assert len(generator.feedback_calls) == 2
    assert len(validator.calls) == 2


class FakeResponses:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.outputs.pop(0))

@pytest.mark.anyio
async def test_malformed_draft_uses_only_one_feedback_retry_before_mandatory_validation():
    from app.clients.ai import ContentGenerationError
    class InvalidThenValid:
        calls = 0
        async def generate_grounded(self, context, issues):
            self.calls += 1
            if self.calls == 1:
                raise ContentGenerationError('fixture', reason='INVALID_GENERATED_OUTPUT')
            assert issues and 'JSON' in issues[0].message
            return grounded_game()
    generator = InvalidThenValid()
    validator = ValidatorStub([PASS])
    result = await generate_grounded_game(research_context(),generator=generator,validator=validator)
    assert result == grounded_game() and generator.calls == 2
    assert len(validator.calls) == 1

@pytest.mark.anyio
async def test_malformed_drafts_never_skip_validation_or_retry_indefinitely():
    from app.clients.ai import ContentGenerationError
    class AlwaysInvalid:
        calls = 0
        async def generate_grounded(self, context, issues):
            self.calls += 1
            raise ContentGenerationError('fixture', reason='INVALID_GENERATED_OUTPUT')
    generator = AlwaysInvalid()
    validator = ValidatorStub([])
    with pytest.raises(ContentGenerationError):
        await generate_grounded_game(research_context(),generator=generator,validator=validator)
    assert generator.calls == 2 and not validator.calls


@pytest.mark.anyio
async def test_deepseek_uses_separate_strict_generation_and_validation_schemas() -> None:
    context = research_context()
    expected_game = grounded_game()
    responses = FakeResponses(
        [
            expected_game.model_dump_json(),
            PASS.model_dump_json(),
        ]
    )
    client = DeepSeekContentGenerator(
        api_key="test-key",
        base_url="https://deepseek.test",
        model="deepseek-v4-flash",
        max_retries=2,
    )
    client.client = SimpleNamespace(responses=responses)
    client.client.with_options = lambda **kwargs: client.client

    draft = await client.generate_grounded(context, issues=[])
    report = await client.validate_grounding(context, draft)

    assert draft == expected_game
    assert report == PASS
    generation_call, validation_call = responses.calls
    assert generation_call["text"]["format"]["schema"]["title"] == (
        "GroundedGeneratedGame"
    )
    assert validation_call["text"]["format"]["schema"]["title"] == (
        "GroundingReport"
    )
    assert "不得引入证据无法支持的新事实" in generation_call["instructions"]
    assert "逐字段" in validation_call["instructions"]
    for field_path in GROUNDING_CHECK_FIELDS:
        assert field_path in validation_call["input"]
    assert "raw_content" not in generation_call["input"]
    assert "raw_content" not in validation_call["input"]
