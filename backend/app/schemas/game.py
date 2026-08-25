from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


Tier = Literal["novice", "advanced", "boss"]


class GeneratedLevel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: Tier
    title: str = Field(min_length=2, max_length=20)
    intro: str = Field(min_length=8, max_length=240)
    question: str = Field(min_length=6, max_length=240)
    options: list[str] = Field(min_length=3, max_length=3)
    correct_option: int = Field(ge=0, le=2)
    wrong_explanation: str = Field(min_length=8, max_length=300)
    praise: str = Field(min_length=4, max_length=100)
    takeaway: str = Field(min_length=4, max_length=100)

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("选项不能为空")
        if len(set(cleaned)) != 3:
            raise ValueError("三个选项必须互不相同")
        return cleaned


class GeneratedGame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    levels: list[GeneratedLevel] = Field(min_length=3, max_length=3)
    summary: list[str] = Field(min_length=3, max_length=3)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("总结知识点不能为空")
        return cleaned

    @model_validator(mode="after")
    def validate_level_order(self) -> "GeneratedGame":
        if [level.tier for level in self.levels] != ["novice", "advanced", "boss"]:
            raise ValueError("关卡顺序必须为 novice、advanced、boss")
        if len(set(self.summary)) != 3:
            raise ValueError("三个总结知识点必须互不相同")
        return self


class GameCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=80)

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("学习主题不能为空")
        return value


class OptionOut(BaseModel):
    index: int
    key: Literal["A", "B", "C"]
    text: str


class LevelOut(BaseModel):
    position: int
    tier: Tier
    title: str
    intro: str
    question: str
    options: list[OptionOut]


class GameOut(BaseModel):
    id: str
    topic: str
    title: str
    status: Literal["active", "paused", "completed"]
    hearts: int = Field(ge=0, le=3)
    current_level: int = Field(ge=0, le=2)
    progress: int = Field(ge=0, le=100)
    level: LevelOut | None
    summary: list[str]
    elapsed_seconds: int | None


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: int = Field(ge=0, le=2)
    attempt_id: UUID


class AnswerResponse(BaseModel):
    result: Literal["correct", "wrong", "paused", "completed"]
    message: str
    explanation: str | None = None
    game: GameOut


class AdReviveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    completed: bool


class ShareResponse(BaseModel):
    token: str
    path: str
    expires_at: datetime
