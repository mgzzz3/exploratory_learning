from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.ai import ContentGenerationError
from app.core.errors import AppError
from app.db.models import LearningSession, Level, User
from app.schemas.learning_input import InputDescriptor
from app.schemas.research import GroundedGeneratedGame, GroundingReport
from app.services.game import create_game
from app.services.generation_strategy import (
    GenerationResult,
    GroundedGenerationStrategy,
    QuestionGenerationStrategy,
)

from .test_grounded_generation import grounded_game, research_context


@dataclass
class RecordingWechat:
    events: list[str]
    allowed: bool = True

    async def check_message(self, openid: str, content: str) -> bool:
        del openid, content
        self.events.append("safety")
        return self.allowed


@dataclass
class RecordingResearcher:
    events: list[str]
    failure: Exception | None = None
    descriptors: list[InputDescriptor] = field(default_factory=list)

    async def research(self, descriptor: InputDescriptor) -> object:
        self.events.append("research")
        self.descriptors.append(descriptor)
        if self.failure is not None:
            raise self.failure
        return object()


@dataclass
class RecordingGroundedClient:
    events: list[str]
    legacy_calls: list[str] = field(default_factory=list)

    async def generate(self, topic: str):
        self.legacy_calls.append(topic)
        raise AssertionError("grounded 请求不得调用 legacy generate")

    async def generate_grounded(self, context, issues) -> GroundedGeneratedGame:
        del context, issues
        self.events.append("generate")
        return grounded_game()

    async def validate_grounding(self, context, game) -> GroundingReport:
        del context, game
        self.events.append("validate")
        return GroundingReport(passed=True, issues=[])


def grounded_strategy(
    events: list[str],
    *,
    researcher: RecordingResearcher | None = None,
    client: RecordingGroundedClient | None = None,
) -> GroundedGenerationStrategy:
    active_researcher = researcher or RecordingResearcher(events)
    active_client = client or RecordingGroundedClient(events)

    def accept(descriptor: InputDescriptor, bundle: object):
        del descriptor, bundle
        events.append("accept")
        return research_context()

    return GroundedGenerationStrategy(
        researcher=active_researcher,
        generator=active_client,
        validator=active_client,
        accept_research=accept,
    )


async def add_user(session: AsyncSession) -> User:
    user = User(openid="pipeline-user")
    session.add(user)
    await session.commit()
    return user


async def row_counts(session: AsyncSession) -> tuple[int, int]:
    sessions = await session.scalar(select(func.count()).select_from(LearningSession))
    levels = await session.scalar(select(func.count()).select_from(Level))
    return int(sessions or 0), int(levels or 0)


@pytest.mark.anyio
async def test_grounded_pipeline_orders_safety_research_accept_generate_validate_then_persist(
    engine,
) -> None:
    events: list[str] = []
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = await add_user(db)
        result = await create_game(
            db,
            user=user,
            topic="Harness Engineering",
            wechat=RecordingWechat(events),
            strategy=grounded_strategy(events),
        )
        events.append("persisted" if await row_counts(db) == (1, 3) else "missing")

    assert result.topic == "Harness Engineering"
    assert events == [
        "safety",
        "research",
        "accept",
        "generate",
        "validate",
        "persisted",
    ]


@pytest.mark.anyio
async def test_blocked_content_has_zero_strategy_calls_and_zero_writes(engine) -> None:
    events: list[str] = []
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = await add_user(db)
        with pytest.raises(AppError) as captured:
            await create_game(
                db,
                user=user,
                topic="违规主题",
                wechat=RecordingWechat(events, allowed=False),
                strategy=grounded_strategy(events),
            )
        counts = await row_counts(db)

    assert captured.value.code == "CONTENT_BLOCKED"
    assert events == ["safety"]
    assert counts == (0, 0)


@pytest.mark.anyio
async def test_grounded_failure_never_calls_legacy_and_writes_nothing(engine) -> None:
    events: list[str] = []
    researcher = RecordingResearcher(
        events,
        failure=ContentGenerationError("research failed"),
    )
    content_client = RecordingGroundedClient(events)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = await add_user(db)
        with pytest.raises(AppError):
            await create_game(
                db,
                user=user,
                topic="Harness Engineering",
                wechat=RecordingWechat(events),
                strategy=grounded_strategy(
                    events,
                    researcher=researcher,
                    client=content_client,
                ),
            )
        counts = await row_counts(db)

    assert events == ["safety", "research"]
    assert content_client.legacy_calls == []
    assert counts == (0, 0)


class CancelledStrategy:
    async def generate(self, descriptor: InputDescriptor) -> GenerationResult:
        del descriptor
        raise asyncio.CancelledError


@pytest.mark.anyio
async def test_cancelled_pipeline_rolls_back_and_propagates_cancellation(engine) -> None:
    events: list[str] = []
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = await add_user(db)
        with pytest.raises(asyncio.CancelledError):
            await create_game(
                db,
                user=user,
                topic="Python 基础",
                wechat=RecordingWechat(events),
                strategy=CancelledStrategy(),
            )
        assert await row_counts(db) == (0, 0)


def test_strategy_protocol_remains_the_only_pipeline_dependency() -> None:
    strategy: QuestionGenerationStrategy = CancelledStrategy()
    assert callable(strategy.generate)
