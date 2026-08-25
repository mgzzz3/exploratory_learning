from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.clients.wechat import WechatClientError
from app.core.errors import AppError
from app.core.security import create_access_token
from app.db.models import User
from app.schemas.auth import AuthUser, LoginResponse, WechatLoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/wechat", response_model=LoginResponse)
async def wechat_login(
    payload: WechatLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    try:
        wx_session = await request.app.state.wechat_client.code_to_session(payload.code)
    except WechatClientError as exc:
        raise AppError(
            status_code=503,
            code="WECHAT_UNAVAILABLE",
            message="微信登录暂时不可用，请稍后再试",
        ) from exc
    user = await db.scalar(select(User).where(User.openid == wx_session.openid))
    if user is None:
        user = User(openid=wx_session.openid, unionid=wx_session.unionid)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif wx_session.unionid and user.unionid != wx_session.unionid:
        user.unionid = wx_session.unionid
        await db.commit()
    settings = request.app.state.settings
    access_token = create_access_token(
        subject=user.id,
        secret=settings.jwt_secret,
        ttl=timedelta(minutes=settings.jwt_ttl_minutes),
    )
    return LoginResponse(
        access_token=access_token,
        user=AuthUser(id=user.id, nickname=user.nickname),
    )
