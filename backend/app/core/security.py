from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt


class InvalidTokenError(ValueError):
    pass


def create_access_token(*, subject: str, secret: str, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + ttl,
        "type": "access",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, secret: str) -> str:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("登录状态已失效") from exc
    subject = payload.get("sub")
    if payload.get("type") != "access" or not isinstance(subject, str):
        raise InvalidTokenError("登录状态无效")
    return subject
