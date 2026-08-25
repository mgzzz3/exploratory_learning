from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.security import InvalidTokenError, create_access_token, decode_access_token


def test_access_token_round_trip() -> None:
    token = create_access_token(
        subject="user-123",
        secret="a-secret-longer-than-thirty-two-characters",
        ttl=timedelta(minutes=5),
    )

    assert decode_access_token(
        token,
        "a-secret-longer-than-thirty-two-characters",
    ) == "user-123"


def test_expired_access_token_is_rejected() -> None:
    token = create_access_token(
        subject="user-123",
        secret="a-secret-longer-than-thirty-two-characters",
        ttl=timedelta(seconds=-1),
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, "a-secret-longer-than-thirty-two-characters")
