from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import User
from app.schemas.user import UserProfile, UserSettings, UserSettingsUpdate

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserProfile)
async def profile(user: User = Depends(get_current_user)) -> UserProfile:
    return UserProfile.model_validate(user, from_attributes=True)


@router.patch("/settings", response_model=UserSettings)
async def update_settings(
    payload: UserSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserSettings:
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(user, key, value)
    await db.commit()
    return UserSettings(
        sound_enabled=user.sound_enabled,
        vibration_enabled=user.vibration_enabled,
        web_search_enabled=user.web_search_enabled,
    )
