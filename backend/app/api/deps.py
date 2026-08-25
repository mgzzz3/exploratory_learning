from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import InvalidTokenError, decode_access_token
from app.db.models import User


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            status_code=401,
            code="UNAUTHORIZED",
            message="请先登录",
        )
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = decode_access_token(token, request.app.state.settings.jwt_secret)
    except InvalidTokenError as exc:
        raise AppError(
            status_code=401,
            code="UNAUTHORIZED",
            message="登录状态已失效，请重新登录",
        ) from exc
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise AppError(
            status_code=401,
            code="UNAUTHORIZED",
            message="登录状态已失效，请重新登录",
        )
    return user
