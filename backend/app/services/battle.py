from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.wechat import WechatClient, WechatClientError
from app.core.errors import AppError
from app.db.models import (
    BattleAnswer,
    BattleParticipant,
    BattleRoom,
    LearningSession,
    Level,
    User,
)
from app.schemas.battle import (
    BattleAnswerResponse,
    BattleParticipantOut,
    BattleQuestionOut,
    BattleResultOut,
    BattleReviewItem,
    BattleRoomOut,
)
from app.schemas.game import OptionOut
from app.schemas.learning_input import InputDescriptor, classify_learning_input
from app.services.game import OPTION_KEYS, _add_levels, aware_utc, now_utc
from app.services.generation_errors import public_generation_error
from app.services.generation_strategy import QuestionGenerationStrategy


WAITING_WINDOW = timedelta(minutes=3)
PLAYING_WINDOW = timedelta(minutes=3)
LEVEL_COUNT = 3


async def create_battle(
    db: AsyncSession,
    *,
    user: User,
    topic: str,
    wechat: WechatClient,
) -> tuple[BattleRoom, InputDescriptor]:
    descriptor = classify_learning_input(topic)
    try:
        allowed = await wechat.check_message(user.openid, descriptor.normalized_input)
    except WechatClientError:
        raise AppError(
            status_code=503,
            code="WECHAT_UNAVAILABLE",
            message="内容安全检查暂时不可用，请稍后再试",
        ) from None
    if not allowed:
        raise AppError(
            status_code=422,
            code="CONTENT_BLOCKED",
            message="这个主题暂时不能生成，换一个试试吧",
        )
    room = BattleRoom(host_user_id=user.id, topic=descriptor.display_topic)
    db.add(room)
    await db.flush()
    db.add(
        BattleParticipant(
            room_id=room.id,
            user_id=user.id,
            role="host",
            status="joined",
        )
    )
    await db.commit()
    return room, descriptor


async def run_battle_generation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    room_id: str,
    descriptor: InputDescriptor,
    strategy: QuestionGenerationStrategy,
) -> None:
    """Background task that turns a generating room into a waiting room."""
    async with session_factory() as db:
        room = await db.get(BattleRoom, room_id)
        if room is None or room.status != "generating":
            return
        try:
            generated = await strategy.generate(descriptor)
        except Exception as exc:
            failure = public_generation_error(exc)
            room.status = "error"
            room.error_message = (
                failure.message if failure is not None else "题目生成失败，请重新发起"
            )
            await db.commit()
            return
        game = LearningSession(
            user_id=room.host_user_id,
            topic=generated.display_topic,
            title=generated.game.title,
            status="active",
            hearts=LEVEL_COUNT,
            current_level=0,
            summary=generated.game.summary,
            input_type=generated.input_type,
            source_input=generated.source_input,
            retrieved_at=generated.retrieved_at,
            sources=[source.model_dump(mode="json") for source in generated.sources],
            generation_mode=generated.generation_mode,
            verification_notice=generated.verification_notice,
            basic_fallback_id=generated.basic_fallback_id,
        )
        db.add(game)
        await db.flush()
        _add_levels(db, game.id, generated.game, generated.level_source_ids)
        room.session_id = game.id
        room.status = "waiting"
        room.expires_at = now_utc() + WAITING_WINDOW
        await db.commit()


async def _get_room(
    db: AsyncSession,
    *,
    room_id: str,
    lock: bool = False,
) -> BattleRoom:
    statement = select(BattleRoom).where(BattleRoom.id == room_id)
    if lock:
        statement = statement.with_for_update()
    room = await db.scalar(statement)
    if room is None:
        raise AppError(
            status_code=404,
            code="BATTLE_NOT_FOUND",
            message="没有找到这场对战",
        )
    return room


async def _get_participants(
    db: AsyncSession,
    *,
    room_id: str,
) -> list[BattleParticipant]:
    result = await db.scalars(
        select(BattleParticipant)
        .where(BattleParticipant.room_id == room_id)
        .order_by(BattleParticipant.created_at)
    )
    return list(result)


async def _get_my_participant(
    db: AsyncSession,
    *,
    room_id: str,
    user_id: str,
) -> BattleParticipant:
    participant = await db.scalar(
        select(BattleParticipant).where(
            BattleParticipant.room_id == room_id,
            BattleParticipant.user_id == user_id,
        )
    )
    if participant is None:
        raise AppError(
            status_code=404,
            code="BATTLE_NOT_FOUND",
            message="没有找到这场对战",
        )
    return participant


def _ranking_key(participant: BattleParticipant) -> tuple[int, int, int]:
    finished = participant.status == "finished"
    return (
        -participant.correct_count,
        0 if finished else 1,
        participant.total_seconds if finished and participant.total_seconds is not None else 0,
    )


async def _settle_playing_room(
    db: AsyncSession,
    *,
    room: BattleRoom,
    participants: list[BattleParticipant],
) -> None:
    if len(participants) != 2:
        return
    first, second = participants
    if first.status == "finished" and second.status == "finished":
        _assign_results(first, second)
        room.status = "finished"
        return
    answer_count = await db.scalar(
        select(BattleAnswer.id)
        .where(BattleAnswer.room_id == room.id)
        .limit(1)
    )
    if answer_count is None:
        room.status = "void"
        return
    _assign_results(first, second)
    room.status = "finished"


def _assign_results(
    first: BattleParticipant,
    second: BattleParticipant,
) -> None:
    first_key = _ranking_key(first)
    second_key = _ranking_key(second)
    if first_key == second_key:
        first.result = "draw"
        second.result = "draw"
    elif first_key < second_key:
        first.result = "win"
        second.result = "lose"
    else:
        first.result = "lose"
        second.result = "win"


async def _apply_lazy_transitions(
    db: AsyncSession,
    *,
    room: BattleRoom,
) -> bool:
    """Void expired waiting rooms and settle finished or timed-out battles."""
    changed = False
    now = now_utc()
    if (
        room.status == "waiting"
        and room.expires_at is not None
        and now > aware_utc(room.expires_at)
    ):
        room.status = "void"
        changed = True
    if room.status == "playing":
        participants = await _get_participants(db, room_id=room.id)
        both_finished = (
            len(participants) == 2
            and all(participant.status == "finished" for participant in participants)
        )
        expired = (
            room.expires_at is not None and now > aware_utc(room.expires_at)
        )
        if both_finished or expired:
            await _settle_playing_room(db, room=room, participants=participants)
            changed = True
    return changed


async def join_battle(
    db: AsyncSession,
    *,
    room_id: str,
    user: User,
) -> BattleRoomOut:
    room = await _get_room(db, room_id=room_id, lock=True)
    if await _apply_lazy_transitions(db, room=room):
        await db.commit()
    if room.host_user_id == user.id:
        raise AppError(
            status_code=409,
            code="BATTLE_SELF_JOIN",
            message="不能加入自己创建的对战",
        )
    existing = await db.scalar(
        select(BattleParticipant).where(
            BattleParticipant.room_id == room_id,
            BattleParticipant.user_id == user.id,
        )
    )
    if existing is not None:
        return await battle_room_to_out(db, room=room, user=user)
    if room.status not in ("generating", "waiting"):
        code = "BATTLE_EXPIRED" if room.status == "void" else "BATTLE_NOT_JOINABLE"
        message = (
            "这场对战已过期，请重新发起"
            if room.status == "void"
            else "这场对战现在不能加入"
        )
        raise AppError(status_code=409, code=code, message=message)
    participants = await _get_participants(db, room_id=room_id)
    if len(participants) >= 2:
        raise AppError(
            status_code=409,
            code="BATTLE_FULL",
            message="对战房间已满",
        )
    db.add(
        BattleParticipant(
            room_id=room.id,
            user_id=user.id,
            role="challenger",
            status="joined",
        )
    )
    await db.commit()
    return await battle_room_to_out(db, room=room, user=user)


async def set_battle_ready(
    db: AsyncSession,
    *,
    room_id: str,
    user: User,
) -> BattleRoomOut:
    room = await _get_room(db, room_id=room_id, lock=True)
    participant = await _get_my_participant(db, room_id=room_id, user_id=user.id)
    if await _apply_lazy_transitions(db, room=room):
        await db.commit()
    if room.status == "error":
        raise AppError(
            status_code=409,
            code="BATTLE_GENERATION_FAILED",
            message=room.error_message or "题目生成失败，请重新发起",
        )
    if room.status == "void":
        raise AppError(
            status_code=409,
            code="BATTLE_EXPIRED",
            message="这场对战已过期，请重新发起",
        )
    if room.status == "generating":
        raise AppError(
            status_code=409,
            code="BATTLE_NOT_READY",
            message="题目还在准备中，稍等一下",
        )
    if room.status in ("finished",):
        raise AppError(
            status_code=409,
            code="BATTLE_FINISHED",
            message="这场对战已经结束了",
        )
    if participant.status == "joined":
        participant.status = "ready"
        participant.ready_at = now_utc()
    participants = await _get_participants(db, room_id=room_id)
    if (
        room.status == "waiting"
        and len(participants) == 2
        and all(item.status == "ready" for item in participants)
    ):
        room.status = "playing"
        room.started_at = now_utc()
        room.expires_at = room.started_at + PLAYING_WINDOW
        for item in participants:
            item.status = "playing"
    await db.commit()
    return await battle_room_to_out(db, room=room, user=user)


async def get_battle_room(
    db: AsyncSession,
    *,
    room_id: str,
    user: User,
) -> BattleRoomOut:
    room = await _get_room(db, room_id=room_id, lock=True)
    await _get_my_participant(db, room_id=room_id, user_id=user.id)
    if await _apply_lazy_transitions(db, room=room):
        await db.commit()
    return await battle_room_to_out(db, room=room, user=user)


async def _level_to_question_out(level: Level) -> BattleQuestionOut:
    return BattleQuestionOut(
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


async def _load_question(
    db: AsyncSession,
    *,
    session_id: str | None,
    position: int,
) -> BattleQuestionOut | None:
    if session_id is None or position >= LEVEL_COUNT:
        return None
    level = await db.scalar(
        select(Level).where(
            Level.session_id == session_id,
            Level.position == position,
        )
    )
    return await _level_to_question_out(level) if level is not None else None


async def answer_battle_question(
    db: AsyncSession,
    *,
    room_id: str,
    user: User,
    option: int,
    attempt_id: UUID,
) -> BattleAnswerResponse:
    room = await _get_room(db, room_id=room_id, lock=True)
    participant = await _get_my_participant(db, room_id=room_id, user_id=user.id)
    if await _apply_lazy_transitions(db, room=room):
        await db.commit()
    if room.status != "playing":
        code = "BATTLE_EXPIRED" if room.status == "void" else "BATTLE_FINISHED"
        message = (
            "这场对战已过期"
            if room.status == "void"
            else "这场对战已经结束了"
        )
        raise AppError(status_code=409, code=code, message=message)
    attempt_key = str(attempt_id)
    existing_attempt = await db.get(BattleAnswer, attempt_key)
    if existing_attempt is not None:
        if (
            existing_attempt.room_id != room.id
            or existing_attempt.participant_id != participant.id
        ):
            raise AppError(
                status_code=409,
                code="BATTLE_ATTEMPT_CONFLICT",
                message="答题请求编号已被使用",
            )
        result = (
            "completed"
            if existing_attempt.level_position == LEVEL_COUNT - 1
            else ("correct" if existing_attempt.is_correct else "wrong")
        )
        return BattleAnswerResponse(
            result=result,
            question=await _load_question(
                db,
                session_id=room.session_id,
                position=participant.current_level,
            ),
        )
    if participant.status == "finished":
        raise AppError(
            status_code=409,
            code="BATTLE_ALREADY_ANSWERED",
            message="你已经答完全部题目",
        )
    position = participant.current_level
    if position >= LEVEL_COUNT:
        raise AppError(
            status_code=500,
            code="BATTLE_DATA_ERROR",
            message="对战答题进度不完整",
        )
    level = await db.scalar(
        select(Level).where(
            Level.session_id == room.session_id,
            Level.position == position,
        )
    )
    if level is None:
        raise AppError(
            status_code=500,
            code="BATTLE_DATA_ERROR",
            message="对战题目数据不完整",
        )
    is_correct = option == level.correct_option
    answered_at = now_utc()
    db.add(
        BattleAnswer(
            id=attempt_key,
            room_id=room.id,
            participant_id=participant.id,
            level_position=position,
            selected_option=option,
            is_correct=is_correct,
            answered_at=answered_at,
        )
    )
    participant.current_level = position + 1
    if is_correct:
        participant.correct_count += 1
    finished = participant.current_level >= LEVEL_COUNT
    if finished:
        participant.status = "finished"
        participant.finished_at = answered_at
        participant.total_seconds = max(
            1,
            int(
                (
                    answered_at - aware_utc(room.started_at)
                ).total_seconds()
            ),
        )
        participants = await _get_participants(db, room_id=room_id)
        if all(item.status == "finished" for item in participants):
            await _settle_playing_room(db, room=room, participants=participants)
    await db.commit()
    result = (
        "completed"
        if finished
        else ("correct" if is_correct else "wrong")
    )
    return BattleAnswerResponse(
        result=result,
        question=await _load_question(
            db,
            session_id=room.session_id,
            position=participant.current_level,
        ),
    )


async def _participant_out(
    db: AsyncSession,
    participant: BattleParticipant,
    *,
    reveal_scores: bool,
) -> BattleParticipantOut:
    nickname = await db.scalar(
        select(User.nickname).where(User.id == participant.user_id)
    )
    return BattleParticipantOut(
        role=participant.role,
        status=participant.status,
        nickname=nickname or "好学的小万",
        correct_count=(
            participant.correct_count
            if reveal_scores or participant.status == "finished"
            else None
        ),
        total_seconds=participant.total_seconds if reveal_scores else None,
        result=participant.result if reveal_scores else None,
    )


async def battle_room_to_out(
    db: AsyncSession,
    *,
    room: BattleRoom,
    user: User,
) -> BattleRoomOut:
    participants = await _get_participants(db, room_id=room.id)
    mine = next(
        (item for item in participants if item.user_id == user.id),
        None,
    )
    if mine is None:
        raise AppError(
            status_code=404,
            code="BATTLE_NOT_FOUND",
            message="没有找到这场对战",
        )
    opponent = next(
        (item for item in participants if item.user_id != user.id),
        None,
    )
    settled = room.status == "finished"
    opponent_out = (
        await _participant_out(db, opponent, reveal_scores=settled)
        if opponent is not None
        else None
    )
    return BattleRoomOut(
        id=room.id,
        topic=room.topic,
        status=room.status,
        error_message=room.error_message,
        started_at=aware_utc(room.started_at) if room.started_at else None,
        expires_at=aware_utc(room.expires_at) if room.expires_at else None,
        me=BattleParticipantOut(
            role=mine.role,
            status=mine.status,
            nickname=user.nickname,
            correct_count=mine.correct_count,
            total_seconds=mine.total_seconds,
            result=mine.result,
        ),
        opponent=opponent_out,
        question=(
            await _load_question(
                db,
                session_id=room.session_id,
                position=mine.current_level,
            )
            if room.status == "playing" and mine.status == "playing"
            else None
        ),
    )


async def get_battle_result(
    db: AsyncSession,
    *,
    room_id: str,
    user: User,
) -> BattleResultOut:
    room = await _get_room(db, room_id=room_id, lock=True)
    participant = await _get_my_participant(db, room_id=room_id, user_id=user.id)
    if await _apply_lazy_transitions(db, room=room):
        await db.commit()
    if room.status != "finished":
        code = "BATTLE_EXPIRED" if room.status == "void" else "BATTLE_NOT_SETTLED"
        message = (
            "这场对战已过期，没有产生结果"
            if room.status == "void"
            else "对战还没有结束，先看看题目吧"
        )
        raise AppError(status_code=409, code=code, message=message)
    participants = await _get_participants(db, room_id=room_id)
    opponent = next(
        (item for item in participants if item.user_id != user.id),
        None,
    )
    review: list[BattleReviewItem] = []
    if participant.status == "finished":
        answers = list(
            await db.scalars(
                select(BattleAnswer)
                .where(BattleAnswer.participant_id == participant.id)
                .order_by(BattleAnswer.level_position)
            )
        )
        levels = list(
            await db.scalars(
                select(Level)
                .where(Level.session_id == room.session_id)
                .order_by(Level.position)
            )
        )
        level_by_position = {level.position: level for level in levels}
        review = [
            BattleReviewItem(
                position=answer.level_position,
                title=level_by_position[answer.level_position].title,
                question=level_by_position[answer.level_position].question,
                options=[
                    OptionOut(
                        index=index,
                        key=OPTION_KEYS[index],
                        text=text,
                    )
                    for index, text in enumerate(
                        level_by_position[answer.level_position].options
                    )
                ],
                selected_option=answer.selected_option,
                correct_option=level_by_position[answer.level_position].correct_option,
                is_correct=answer.is_correct,
                explanation=(
                    level_by_position[answer.level_position].praise
                    if answer.is_correct
                    else level_by_position[answer.level_position].wrong_explanation
                ),
            )
            for answer in answers
        ]
    return BattleResultOut(
        room_id=room.id,
        topic=room.topic,
        status=room.status,
        my_result=participant.result,
        opponent_result=opponent.result if opponent is not None else None,
        my_correct_count=participant.correct_count,
        opponent_correct_count=(
            opponent.correct_count if opponent is not None else None
        ),
        my_total_seconds=participant.total_seconds,
        opponent_total_seconds=(
            opponent.total_seconds if opponent is not None else None
        ),
        review=review,
    )
