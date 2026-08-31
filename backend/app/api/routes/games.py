from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.request_lifecycle import run_until_disconnect
from app.core.errors import AppError
from app.core.observability import request_id as current_request_id, note_admission
from app.services.basic_permits import FallbackPermits
from app.services.basic_knowledge import BasicKnowledgeService
from app.db.models import User
from app.schemas.game import (
    AdReviveRequest,
    AnswerRequest,
    AnswerResponse,
    GameCreateRequest,
    BasicGameCreateRequest,
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
    request_id = current_request_id()
    async def operation():
        try:
            return await create_game(
                db, user=user, topic=payload.topic,
                wechat=request.app.state.wechat_client,
                strategy=request.app.state.generation_strategy,
            )
        except AppError as exc:
            settings = request.app.state.settings
            permits = FallbackPermits(secret=settings.jwt_secret, mode=settings.question_generation_mode)
            fallback = permits.issue(user_id=user.id, topic=payload.topic, request_id=request_id, error=exc)
            note_admission(fallback["available"])
            exc.details = {**(exc.details or {}), "request_id": request_id, "fallback": fallback}
            raise
    return await run_until_disconnect(request, operation)


@router.post("/basic", response_model=GameOut, status_code=status.HTTP_201_CREATED)
async def create_basic(
    payload: BasicGameCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GameOut:
    request_id = current_request_id()
    settings = request.app.state.settings
    service = BasicKnowledgeService(
        wechat=request.app.state.wechat_client,
        generator=request.app.state.content_generator,
        permits=FallbackPermits(secret=settings.jwt_secret, mode=settings.question_generation_mode),
    )
    async def operation():
        try:
            return await service.create(db, user=user, payload=payload)
        except AppError as exc:
            exc.details = {**(exc.details or {}), "request_id": request_id, "fallback": {"available": False}}
            raise
    return await run_until_disconnect(request, operation)


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
