from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import User
from app.schemas.game import GameOut
from app.services.game import assist_friend

router = APIRouter(prefix="/assists", tags=["assists"])


@router.post("/{token}", response_model=GameOut)
async def assist(
    token: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GameOut:
    return await assist_friend(db, helper=user, token=token)
