from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.game import OptionOut, Tier
from app.schemas.learning_input import classify_learning_input


BattleRoomStatus = Literal[
    "generating",
    "waiting",
    "playing",
    "finished",
    "void",
    "error",
]
BattleRole = Literal["host", "challenger"]
BattleParticipantStatus = Literal["joined", "ready", "playing", "finished"]
BattleOutcome = Literal["win", "lose", "draw"]


class BattleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=2048)

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        return classify_learning_input(value).normalized_input


class BattleParticipantOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: BattleRole
    status: BattleParticipantStatus
    nickname: str
    correct_count: int | None = None
    total_seconds: int | None = None
    result: BattleOutcome | None = None


class BattleQuestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    tier: Tier
    title: str
    intro: str
    question: str
    options: list[OptionOut]


class BattleRoomOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    topic: str
    status: BattleRoomStatus
    error_message: str | None = None
    started_at: datetime | None = None
    expires_at: datetime | None = None
    me: BattleParticipantOut
    opponent: BattleParticipantOut | None = None
    question: BattleQuestionOut | None = None


class BattleAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: int = Field(ge=0, le=2)
    attempt_id: UUID


class BattleAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Literal["correct", "wrong", "completed"]
    question: BattleQuestionOut | None = None


class BattleReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    title: str
    question: str
    options: list[OptionOut]
    selected_option: int
    correct_option: int
    is_correct: bool
    explanation: str


class BattleResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: str
    topic: str
    status: BattleRoomStatus
    my_result: BattleOutcome | None = None
    opponent_result: BattleOutcome | None = None
    my_correct_count: int = 0
    opponent_correct_count: int | None = None
    my_total_seconds: int | None = None
    opponent_total_seconds: int | None = None
    review: list[BattleReviewItem] = Field(default_factory=list)
