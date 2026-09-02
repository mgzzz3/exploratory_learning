from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UserProfile(BaseModel):
    id: str
    nickname: str
    completed_games: int
    learned_points: int
    sound_enabled: bool
    vibration_enabled: bool
    web_search_enabled: bool


class UserSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sound_enabled: bool | None = None
    vibration_enabled: bool | None = None
    web_search_enabled: bool | None = None


class UserSettings(BaseModel):
    sound_enabled: bool
    vibration_enabled: bool
    web_search_enabled: bool
