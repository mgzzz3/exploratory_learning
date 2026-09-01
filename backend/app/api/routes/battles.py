from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import User
from app.schemas.battle import (
    BattleAnswerRequest,
    BattleAnswerResponse,
    BattleCreateRequest,
    BattleResultOut,
    BattleRoomOut,
)
from app.services.battle import (
    answer_battle_question,
    battle_room_to_out,
    create_battle,
    get_battle_result,
    get_battle_room,
    join_battle,
    run_battle_generation,
    set_battle_ready,
)


router = APIRouter(prefix="/battles", tags=["battles"])


@router.post("", response_model=BattleRoomOut, status_code=status.HTTP_201_CREATED)
async def create(
    payload: BattleCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BattleRoomOut:
    room, descriptor = await create_battle(
        db,
        user=user,
        topic=payload.topic,
        wechat=request.app.state.wechat_client,
    )
    background_tasks.add_task(
        run_battle_generation,
        request.app.state.session_factory,
        room_id=room.id,
        descriptor=descriptor,
        strategy=request.app.state.generation_strategy,
    )
    return await battle_room_to_out(db, room=room, user=user)


@router.get("/{room_id}", response_model=BattleRoomOut)
async def detail(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BattleRoomOut:
    return await get_battle_room(db, room_id=room_id, user=user)


@router.post("/{room_id}/join", response_model=BattleRoomOut)
async def join(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BattleRoomOut:
    return await join_battle(db, room_id=room_id, user=user)


@router.post("/{room_id}/ready", response_model=BattleRoomOut)
async def ready(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BattleRoomOut:
    return await set_battle_ready(db, room_id=room_id, user=user)


@router.post("/{room_id}/answers", response_model=BattleAnswerResponse)
async def answer(
    room_id: str,
    payload: BattleAnswerRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BattleAnswerResponse:
    return await answer_battle_question(
        db,
        room_id=room_id,
        user=user,
        option=payload.option,
        attempt_id=payload.attempt_id,
    )


@router.get("/{room_id}/result", response_model=BattleResultOut)
async def result(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BattleResultOut:
    return await get_battle_result(db, room_id=room_id, user=user)
