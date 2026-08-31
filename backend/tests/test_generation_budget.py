from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.clients.ai import DeepSeekContentGenerator
from app.schemas.learning_input import classify_learning_input
from app.services.generation_strategy import GroundedGenerationStrategy
from app.services.grounded_generation import generate_grounded_game

from .test_grounded_generation import (
    DraftGeneratorStub, ValidatorStub, PASS, UNSUPPORTED_INTRO,
    grounded_game, research_context,
)
from .test_research_agent_runtime import setup_agent, search_call, extract_call, finish


@dataclass
class Clock:
    now: float = 100.0

    def __call__(self):
        return self.now


def start_budget(clock=None, **kwargs):
    from app.core.generation_budget import GenerationBudget
    return GenerationBudget.start(clock=clock or Clock(), **kwargs)


def test_budget_has_one_absolute_deadline_and_reserved_stage_cutoffs():
    budget = start_budget()
    assert budget.started_at == 100
    assert budget.deadline == 185
    assert budget.research_deadline == 145
    assert budget.exploration_deadline == 130
    assert budget.cutoff("generation") == 170
    assert budget.cutoff("validation") == 185


@pytest.mark.anyio
@pytest.mark.parametrize("stage,elapsed,reason", [
    ("research", 45, "RESEARCH_TIMEOUT"),
    ("generation", 70, "GENERATION_TIMEOUT"),
    ("validation", 85, "VALIDATION_TIMEOUT"),
])
async def test_stage_rejects_expired_budget_before_external_call(stage, elapsed, reason):
    from app.core.generation_budget import GenerationDeadlineError
    clock = Clock()
    budget = start_budget(clock)
    clock.now += elapsed
    called = False
    with pytest.raises(GenerationDeadlineError) as caught:
        async with budget.stage(stage):
            called = True
    assert not called
    assert caught.value.reason == reason


@pytest.mark.anyio
async def test_active_budget_is_request_local_and_reset_even_after_failure():
    from app.core.generation_budget import current_generation_budget
    budget = start_budget()
    assert current_generation_budget() is None
    with pytest.raises(ValueError):
        async with budget.activate():
            assert current_generation_budget() is budget
            raise ValueError("offline test")
    assert current_generation_budget() is None


@pytest.mark.anyio
async def test_early_research_releases_unused_time_to_generation_and_validation():
    from app.core.generation_budget import current_generation_budget
    clock = Clock()
    budget = start_budget(clock)
    seen = []

    class Research:
        async def research(self, descriptor):
            seen.append(current_generation_budget())
            clock.now += 10
            return object()

    class Client:
        async def generate_grounded(self, context, issues):
            seen.append(current_generation_budget())
            clock.now += 55
            return grounded_game()

        async def validate_grounding(self, context, game):
            seen.append(current_generation_budget())
            clock.now += 19
            return PASS

    client = Client()
    strategy = GroundedGenerationStrategy(
        researcher=Research(), generator=client, validator=client,
        accept_research=lambda *_: research_context(), budget_factory=lambda: budget,
    )
    result = await strategy.generate(classify_learning_input("Harness Engineering"))
    assert result.game == grounded_game()
    assert seen == [budget, budget, budget]
    assert clock.now == 184
    assert current_generation_budget() is None


@pytest.mark.anyio
async def test_regeneration_cannot_consume_time_reserved_for_validation():
    from app.core.generation_budget import GenerationDeadlineError
    clock = Clock()
    budget = start_budget(clock)
    clock.now = 145

    class Generator(DraftGeneratorStub):
        async def generate_grounded(self, context, issues):
            clock.now += 10
            return await super().generate_grounded(context, issues)

    class Validator(ValidatorStub):
        async def validate_grounding(self, context, game):
            clock.now += 16
            return await super().validate_grounding(context, game)

    generator = Generator([grounded_game(), grounded_game()])
    validator = Validator([UNSUPPORTED_INTRO, PASS])
    with pytest.raises(GenerationDeadlineError) as caught:
        async with budget.activate():
            await generate_grounded_game(research_context(), generator=generator, validator=validator)
    assert caught.value.reason == "GENERATION_TIMEOUT"
    assert len(generator.feedback_calls) == 1
    assert len(validator.calls) == 1
    assert budget.deadline == 185


@pytest.mark.anyio
async def test_draft_that_used_reserved_validation_time_is_rejected():
    from app.core.generation_budget import GenerationDeadlineError
    clock = Clock()
    budget = start_budget(clock)

    class SlowGenerator(DraftGeneratorStub):
        async def generate_grounded(self, context, issues):
            clock.now = 171
            return await super().generate_grounded(context, issues)

    generator = SlowGenerator([grounded_game()])
    validator = ValidatorStub([PASS])
    with pytest.raises(GenerationDeadlineError):
        async with budget.activate():
            await generate_grounded_game(research_context(), generator=generator, validator=validator)
    assert not validator.calls


@pytest.mark.anyio
async def test_only_one_fact_feedback_regeneration_is_allowed():
    generator = DraftGeneratorStub([grounded_game()] * 3)
    with pytest.raises(ValueError):
        await generate_grounded_game(
            research_context(), generator=generator,
            validator=ValidatorStub([UNSUPPORTED_INTRO] * 3), max_regenerations=2,
        )
    assert not generator.feedback_calls


@pytest.mark.anyio
async def test_exploration_cutoff_blocks_new_search_but_retains_prior_evidence():
    clock = Clock()
    budget = start_budget(clock)

    def late_search(messages, names):
        clock.now = 131
        return search_call(2)

    agent, _, search, _, _ = setup_agent([search_call(1), late_search, finish])
    async with budget.activate():
        result = await agent.research(classify_learning_input("高情商聊天"))
    assert result.status == "ready"
    assert len(search.calls) == 1


@pytest.mark.anyio
async def test_window_expiry_cancels_inflight_tool_then_finalizes_existing_evidence():
    cancelled = asyncio.Event()

    class WaitingExtract:
        async def extract(self, params, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    from app.core.generation_budget import GenerationBudget
    budget = GenerationBudget.start(
        total_seconds=0.3, generation_reserve_seconds=0.1,
        finalization_reserve_seconds=0.1, validation_reserve_seconds=0.05,
    )
    agent, model, search, _, _ = setup_agent([search_call(), extract_call(), finish], extract=WaitingExtract())
    async with budget.activate():
        result = await agent.research(classify_learning_input("高情商聊天"))
    assert cancelled.is_set()
    assert result.status == "ready"
    assert len(search.calls) == 1
    assert len(model.seen) == 3


@pytest.mark.anyio
async def test_total_deadline_cancels_validation_instead_of_returning_draft():
    from app.core.generation_budget import GenerationBudget, GenerationDeadlineError
    cancelled = asyncio.Event()

    class WaitingValidator:
        async def validate_grounding(self, context, game):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    budget = GenerationBudget.start(
        total_seconds=0.06, generation_reserve_seconds=0.02,
        finalization_reserve_seconds=0.01, validation_reserve_seconds=0.01,
    )
    with pytest.raises(GenerationDeadlineError) as caught:
        async with budget.activate():
            await generate_grounded_game(
                research_context(), generator=DraftGeneratorStub([grounded_game()]),
                validator=WaitingValidator(),
            )
    assert caught.value.reason == "VALIDATION_TIMEOUT"
    assert cancelled.is_set()


@pytest.mark.anyio
async def test_grounded_sdk_options_do_not_mutate_legacy_client():
    generator = DeepSeekContentGenerator(api_key="offline-placeholder", base_url="https://example.com", model="configured-model", max_retries=3)
    root_client = generator.client
    assert root_client.max_retries == 2
    budget = start_budget()
    async with budget.activate():
        grounded_client = generator._grounded_client("generation")
        assert grounded_client.max_retries == 0
        assert grounded_client.timeout == 70
        assert root_client.max_retries == 2
        assert generator.max_retries == 3
    await root_client.close()
