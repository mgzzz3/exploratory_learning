from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from app.core.errors import AppError


GenerationStage = Literal["research", "generation", "validation"]
_CURRENT: ContextVar[GenerationBudget | None] = ContextVar("generation_budget", default=None)


class GenerationDeadlineError(AppError):
    def __init__(self, stage: GenerationStage) -> None:
        self.reason = {
            "research": "RESEARCH_TIMEOUT",
            "generation": "GENERATION_TIMEOUT",
            "validation": "VALIDATION_TIMEOUT",
        }[stage]
        super().__init__(
            status_code=502,
            code="RESEARCH_AGENT_FAILED" if stage == "research" else "AI_GENERATION_FAILED",
            message="生成时间预算已用尽，请稍后重试",
            details={"reason": self.reason},
        )


@dataclass
class GenerationBudget:
    started_at: float
    deadline: float
    research_deadline: float
    exploration_deadline: float
    validation_reserve_seconds: float
    clock: Callable[[], float] = field(repr=False)
    active_stage: GenerationStage = "research"

    @classmethod
    def start(
        cls, *, total_seconds: float = 85, generation_reserve_seconds: float = 40,
        finalization_reserve_seconds: float = 15, validation_reserve_seconds: float = 15,
        clock: Callable[[], float] = time.monotonic,
    ) -> GenerationBudget:
        if not (
            0 < total_seconds <= 85
            and 0 < validation_reserve_seconds < generation_reserve_seconds < total_seconds
            and 0 < finalization_reserve_seconds < total_seconds - generation_reserve_seconds
        ):
            raise ValueError("生成预算预留关系无效")
        started = clock()
        deadline = started + total_seconds
        research_deadline = deadline - generation_reserve_seconds
        return cls(
            started, deadline, research_deadline,
            research_deadline - finalization_reserve_seconds,
            validation_reserve_seconds, clock,
        )

    def cutoff(self, stage: GenerationStage) -> float:
        return {
            "research": self.research_deadline,
            "generation": self.deadline - self.validation_reserve_seconds,
            "validation": self.deadline,
        }[stage]

    def remaining(self, stage: GenerationStage) -> float:
        return max(0.0, self.cutoff(stage) - self.clock())

    def loop_deadline(self, cutoff: float) -> float:
        # Production uses the same monotonic clock as asyncio. Conversion also
        # lets tests advance a fake clock without resetting the original budget.
        return asyncio.get_running_loop().time() + max(0.0, cutoff - self.clock())

    def require_time(self, stage: GenerationStage) -> None:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if self.remaining(stage) <= 0:
            raise GenerationDeadlineError(stage)

    @asynccontextmanager
    async def activate(self):
        token = _CURRENT.set(self)
        timer = asyncio.timeout_at(self.loop_deadline(self.deadline))
        try:
            async with timer:
                yield self
                if self.clock() >= self.deadline:
                    raise GenerationDeadlineError(self.active_stage)
        except TimeoutError:
            if timer.expired():
                raise GenerationDeadlineError(self.active_stage) from None
            raise
        finally:
            _CURRENT.reset(token)

    @asynccontextmanager
    async def stage(self, stage: GenerationStage):
        self.active_stage = stage
        self.require_time(stage)
        timer = asyncio.timeout_at(self.loop_deadline(self.cutoff(stage)))
        try:
            async with timer:
                yield
                self.require_time(stage)
        except TimeoutError:
            if timer.expired():
                raise GenerationDeadlineError(stage) from None
            raise


def current_generation_budget() -> GenerationBudget | None:
    return _CURRENT.get()


@asynccontextmanager
async def generation_stage(stage: GenerationStage):
    budget = current_generation_budget()
    if budget is None:
        yield
    else:
        async with budget.stage(stage):
            yield
