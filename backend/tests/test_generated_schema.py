from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.game import GeneratedGame

from .fakes import generated_game


def test_generated_game_requires_exactly_three_levels() -> None:
    payload = generated_game("Python 基础").model_dump()
    payload["levels"] = payload["levels"][:2]

    with pytest.raises(ValidationError):
        GeneratedGame.model_validate(payload)


def test_generated_level_requires_three_unique_options() -> None:
    payload = generated_game("Python 基础").model_dump()
    payload["levels"][0]["options"] = ["一样", "一样", "另一个"]

    with pytest.raises(ValidationError):
        GeneratedGame.model_validate(payload)


def test_generated_levels_must_follow_novice_advanced_boss_order() -> None:
    payload = generated_game("Python 基础").model_dump()
    payload["levels"][0]["tier"] = "boss"

    with pytest.raises(ValidationError):
        GeneratedGame.model_validate(payload)


def test_correct_option_must_point_to_an_existing_option() -> None:
    payload = generated_game("Python 基础").model_dump()
    payload["levels"][0]["correct_option"] = 3

    with pytest.raises(ValidationError):
        GeneratedGame.model_validate(payload)


def test_generated_game_rejects_blank_summary_item() -> None:
    payload = generated_game("Python 基础").model_dump()
    payload["summary"][1] = "   "

    with pytest.raises(ValidationError):
        GeneratedGame.model_validate(payload)
