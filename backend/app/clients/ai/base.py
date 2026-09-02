from __future__ import annotations

from typing import Protocol

from app.schemas.game import GeneratedGame
from app.schemas.research import (
    GroundingIssue,
    GroundedGeneratedGame,
    GroundingReport,
    ResearchContext,
)


class ContentGenerationError(RuntimeError):
    def __init__(self, message: str, *, reason: str = "GENERATION_UNAVAILABLE") -> None:
        super().__init__(message)
        self.reason = reason


class ContentGenerator(Protocol):
    async def generate(self, topic: str) -> GeneratedGame: ...


class GroundedContentGenerator(Protocol):
    async def generate_grounded(
        self,
        context: ResearchContext,
        issues: list[GroundingIssue],
    ) -> GroundedGeneratedGame: ...


class GroundingValidator(Protocol):
    async def validate_grounding(
        self,
        context: ResearchContext,
        game: GroundedGeneratedGame,
    ) -> GroundingReport: ...
