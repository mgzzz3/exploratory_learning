from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import User
from app.schemas.game import (
    AdReviveRequest,
    AnswerRequest,
    AnswerResponse,
    GameCreateRequest,
    GameOut,
    ShareResponse,
)
from app.services.game import (
    answer_game,
    create_game,
    create_share,
    game_to_out,
    get_owned_game,
    revive_with_ad,
)

router = APIRouter(prefix="/games", tags=["games"])


@router.post("", response_model=GameOut, status_code=status.HTTP_201_CREATED)
async def create(
    payload: GameCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GameOut:
    return await create_game(
        db,
        user=user,
        topic=payload.topic,
        wechat=request.app.state.wechat_client,
        generator=request.app.state.content_generator,
    )


@router.get("/{game_id}", response_model=GameOut)
async def detail(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GameOut:
    game = await get_owned_game(db, game_id=game_id, user_id=user.id)
    return await game_to_out(db, game)


@router.post("/{game_id}/answers", response_model=AnswerResponse)
async def answer(
    game_id: str,
    payload: AnswerRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnswerResponse:
    return await answer_game(db, user=user, game_id=game_id, request=payload)


@router.post("/{game_id}/revives/ad", response_model=GameOut)
async def revive_ad(
    game_id: str,
    payload: AdReviveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GameOut:
    return await revive_with_ad(db, user=user, game_id=game_id, request=payload)


@router.post(
    "/{game_id}/share",
    response_model=ShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def share(
    game_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ShareResponse:
    return await create_share(db, user=user, game_id=game_id)
