from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai import ContentGenerationError, ContentGenerator
from app.clients.wechat import WechatClient, WechatClientError
from app.core.errors import AppError
from app.db.models import (
    AnswerAttempt,
    AssistToken,
    LearningSession,
    Level,
    ReviveEvent,
    User,
)
from app.schemas.game import (
    AdReviveRequest,
    AnswerRequest,
    AnswerResponse,
    GameOut,
    GeneratedGame,
    LevelOut,
    OptionOut,
    ShareResponse,
)


OPTION_KEYS = ("A", "B", "C")
PROGRESS = (18, 52, 84)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def get_owned_game(
    db: AsyncSession,
    *,
    game_id: str,
    user_id: str,
    lock: bool = False,
) -> LearningSession:
    statement = select(LearningSession).where(
        LearningSession.id == game_id,
        LearningSession.user_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    game = await db.scalar(statement)
    if game is None:
        raise AppError(status_code=404, code="GAME_NOT_FOUND", message="没有找到这次学习")
    return game


async def game_to_out(db: AsyncSession, game: LearningSession) -> GameOut:
    level_out: LevelOut | None = None
    if game.status != "completed":
        level = await db.scalar(
            select(Level).where(
                Level.session_id == game.id,
                Level.position == game.current_level,
            )
        )
        if level is not None:
            level_out = LevelOut(
                position=level.position,
                tier=level.tier,
                title=level.title,
                intro=level.intro,
                question=level.question,
                options=[
                    OptionOut(index=index, key=OPTION_KEYS[index], text=text)
                    for index, text in enumerate(level.options)
                ],
            )
    progress = 100 if game.status == "completed" else PROGRESS[game.current_level]
    return GameOut(
        id=game.id,
        topic=game.topic,
        title=game.title,
        status=game.status,
        hearts=game.hearts,
        current_level=game.current_level,
        progress=progress,
        level=level_out,
        summary=game.summary,
        elapsed_seconds=game.elapsed_seconds,
    )


async def create_game(
    db: AsyncSession,
    *,
    user: User,
    topic: str,
    wechat: WechatClient,
    generator: ContentGenerator,
) -> GameOut:
    try:
        allowed = await wechat.check_message(user.openid, topic)
    except WechatClientError as exc:
        raise AppError(
            status_code=503,
            code="WECHAT_UNAVAILABLE",
            message="内容安全检查暂时不可用，请稍后再试",
        ) from exc
    if not allowed:
        raise AppError(
            status_code=422,
            code="CONTENT_BLOCKED",
            message="这个主题暂时不能生成，换一个试试吧",
        )
    try:
        generated = await generator.generate(topic)
    except ContentGenerationError as exc:
        raise AppError(
            status_code=502,
            code="AI_GENERATION_FAILED",
            message="这次没搭好关卡，请重新生成",
            details={"topic": topic},
        ) from exc
    game = LearningSession(
        user_id=user.id,
        topic=topic,
        title=generated.title,
        status="active",
        hearts=3,
        current_level=0,
        summary=generated.summary,
    )
    db.add(game)
    await db.flush()
    _add_levels(db, game.id, generated)
    await db.commit()
    return await game_to_out(db, game)


def _add_levels(db: AsyncSession, session_id: str, generated: GeneratedGame) -> None:
    for position, level in enumerate(generated.levels):
        db.add(
            Level(
                session_id=session_id,
                position=position,
                tier=level.tier,
                title=level.title,
                intro=level.intro,
                question=level.question,
                options=level.options,
                correct_option=level.correct_option,
                wrong_explanation=level.wrong_explanation,
                praise=level.praise,
                takeaway=level.takeaway,
            )
        )


async def answer_game(
    db: AsyncSession,
    *,
    user: User,
    game_id: str,
    request: AnswerRequest,
) -> AnswerResponse:
    attempt_key = str(request.attempt_id)
    existing = await db.get(AnswerAttempt, attempt_key)
    if existing is not None:
        if existing.user_id != user.id or existing.session_id != game_id:
            raise AppError(
                status_code=409,
                code="ATTEMPT_ID_CONFLICT",
                message="答题请求编号已被使用",
            )
        return AnswerResponse.model_validate(existing.response_payload)

    game = await get_owned_game(db, game_id=game_id, user_id=user.id, lock=True)
    if game.status == "paused":
        raise AppError(status_code=409, code="GAME_PAUSED", message="先补充脑力再继续闯关")
    if game.status == "completed":
        raise AppError(status_code=409, code="GAME_COMPLETED", message="这次学习已经完成啦")

    level = await db.scalar(
        select(Level).where(
            Level.session_id == game.id,
            Level.position == game.current_level,
        )
    )
    if level is None:
        raise AppError(status_code=500, code="GAME_DATA_ERROR", message="关卡数据不完整")

    correct = request.option == level.correct_option
    if correct and game.current_level == 2:
        game.status = "completed"
        game.completed_at = now_utc()
        game.elapsed_seconds = max(
            1,
            int((game.completed_at - aware_utc(game.started_at)).total_seconds()),
        )
        user.completed_games += 1
        user.learned_points += 3
        result = "completed"
        message = level.praise
        explanation = None
    elif correct:
        game.current_level += 1
        result = "correct"
        message = level.praise
        explanation = None
    else:
        game.hearts = max(0, game.hearts - 1)
        if game.hearts == 0:
            game.status = "paused"
            result = "paused"
            message = "脑力用完啦，补满后再战"
        else:
            result = "wrong"
            message = "差一点，再看一眼这个比喻"
        explanation = level.wrong_explanation

    response = AnswerResponse(
        result=result,
        message=message,
        explanation=explanation,
        game=await game_to_out(db, game),
    )
    db.add(
        AnswerAttempt(
            id=attempt_key,
            session_id=game.id,
            user_id=user.id,
            level_position=level.position,
            selected_option=request.option,
            is_correct=correct,
            hearts_after=game.hearts,
            response_payload=response.model_dump(mode="json"),
        )
    )
    await db.commit()
    return response


async def revive_with_ad(
    db: AsyncSession,
    *,
    user: User,
    game_id: str,
    request: AdReviveRequest,
) -> GameOut:
    event_key = str(request.event_id)
    existing = await db.get(ReviveEvent, event_key)
    if existing is not None:
        if existing.session_id != game_id or existing.actor_user_id != user.id:
            raise AppError(
                status_code=409,
                code="REVIVE_ID_CONFLICT",
                message="复活请求编号已被使用",
            )
        game = await get_owned_game(db, game_id=game_id, user_id=user.id)
        return await game_to_out(db, game)
    if not request.completed:
        raise AppError(
            status_code=422,
            code="AD_NOT_COMPLETED",
            message="看完视频才能恢复脑力",
        )
    game = await get_owned_game(db, game_id=game_id, user_id=user.id, lock=True)
    if game.status != "paused":
        raise AppError(status_code=409, code="GAME_NOT_PAUSED", message="当前不需要补充脑力")
    game.hearts = 3
    game.status = "active"
    db.add(
        ReviveEvent(
            id=event_key,
            session_id=game.id,
            method="ad",
            actor_user_id=user.id,
        )
    )
    await db.commit()
    return await game_to_out(db, game)


async def create_share(
    db: AsyncSession,
    *,
    user: User,
    game_id: str,
) -> ShareResponse:
    game = await get_owned_game(db, game_id=game_id, user_id=user.id)
    if game.status != "paused":
        raise AppError(status_code=409, code="GAME_NOT_PAUSED", message="脑力用完时才能请好友帮忙")
    token = secrets.token_urlsafe(24)
    expires_at = now_utc() + timedelta(hours=24)
    db.add(
        AssistToken(
            token=token,
            session_id=game.id,
            owner_user_id=user.id,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return ShareResponse(
        token=token,
        path=f"/pages/assist/index?token={token}",
        expires_at=expires_at,
    )


async def assist_friend(
    db: AsyncSession,
    *,
    helper: User,
    token: str,
) -> GameOut:
    assist = await db.scalar(
        select(AssistToken).where(AssistToken.token == token).with_for_update()
    )
    if assist is None:
        raise AppError(status_code=404, code="ASSIST_NOT_FOUND", message="这张助力卡不存在")
    if assist.owner_user_id == helper.id:
        raise AppError(
            status_code=409,
            code="SELF_ASSIST_NOT_ALLOWED",
            message="需要另一位好友来帮忙",
        )
    if assist.status == "used":
        raise AppError(status_code=409, code="ASSIST_ALREADY_USED", message="这张助力卡已经用过啦")
    if aware_utc(assist.expires_at) <= now_utc():
        assist.status = "expired"
        await db.commit()
        raise AppError(status_code=410, code="ASSIST_EXPIRED", message="这张助力卡已经过期")
    game = await db.get(LearningSession, assist.session_id, with_for_update=True)
    if game is None:
        raise AppError(status_code=404, code="GAME_NOT_FOUND", message="没有找到这次学习")
    if game.status != "paused":
        raise AppError(status_code=409, code="GAME_NOT_PAUSED", message="好友已经恢复脑力啦")
    game.hearts = 3
    game.status = "active"
    assist.status = "used"
    assist.assisted_by = helper.id
    assist.used_at = now_utc()
    db.add(
        ReviveEvent(
            id=f"assist:{assist.token}",
            session_id=game.id,
            method="share",
            actor_user_id=helper.id,
        )
    )
    await db.commit()
    return await game_to_out(db, game)
