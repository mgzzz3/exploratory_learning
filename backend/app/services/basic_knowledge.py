from __future__ import annotations

import asyncio

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.request_lifecycle import require_connected_task
from app.clients.ai import ContentGenerationError, ContentGenerator
from app.clients.wechat import WechatClient, WechatClientError
from app.core.errors import AppError
from app.core.observability import note_admission, stage, record_counts
from app.db.models import User
from app.schemas.game import BasicGameCreateRequest, GameOut, GeneratedGame
from app.services.basic_permits import FallbackPermits
from app.services.basic_policy import NOTICE
from app.services.game import find_basic_game, persist_generated_game
from app.services.generation_strategy import GenerationResult


class BasicKnowledgeService:
    def __init__(self, *, wechat: WechatClient, generator: ContentGenerator, permits: FallbackPermits, timeout_seconds: float = 85) -> None:
        if not 0 < timeout_seconds <= 85:
            raise ValueError("basic 总预算必须大于 0 且不超过 85 秒")
        self._wechat, self._generator, self._permits = wechat, generator, permits
        self._timeout = timeout_seconds

    async def create(self, db: AsyncSession, *, user: User, payload: BasicGameCreateRequest) -> GameOut:
        user_id, openid = user.id, user.openid
        with stage("admission"):
            try:
                permit = self._permits.verify(payload.fallback_token, user_id=user_id, topic=payload.topic)
            except AppError:
                note_admission(False)
                raise
            note_admission(True, parent_request_id=permit.parent_request_id)
        existing = await find_basic_game(db, user_id=user_id, permit_id=permit.id)
        if existing is not None:
            return existing
        # End the authorization/replay read transaction before external calls.
        # Primitive identity values above remain usable after rollback expires ORM objects.
        await db.rollback()
        safety_failure = None
        try:
            with stage("safety"):
                allowed = await self._wechat.check_message(openid, payload.topic)
        except WechatClientError:
            safety_failure = AppError(status_code=503, code="WECHAT_UNAVAILABLE", message="内容安全检查暂时不可用，请稍后再试")
        if safety_failure:
            raise safety_failure from None
        if not allowed:
            raise AppError(status_code=422, code="CONTENT_BLOCKED", message="这个主题暂时不能生成，换一个试试吧")
        require_connected_task()
        failure = None
        try:
            deadline = asyncio.get_running_loop().time() + self._timeout
            async with asyncio.timeout_at(deadline):
                with stage("generation"):
                    record_counts(model_calls=1)
                    raw = await self._generator.generate(payload.topic)
                    # Revalidate even an injected/generated model instance, including all three levels.
                    game = GeneratedGame.model_validate(raw.model_dump() if isinstance(raw, GeneratedGame) else raw)
                    require_connected_task()
        except asyncio.CancelledError:
            await db.rollback()
            raise
        except TimeoutError:
            failure = "GENERATION_TIMEOUT"
        except ValidationError:
            failure = "INVALID_GENERATED_OUTPUT"
        except ContentGenerationError:
            failure = "GENERATION_UNAVAILABLE"
        if failure:
            raise AppError(status_code=502, code="AI_GENERATION_FAILED", message="基础知识关卡未能生成，请主动重试", details={"reason": failure}) from None
        result = GenerationResult(
            game=game, display_topic=payload.topic, input_type="keyword", level_source_ids=[[], [], []],
            generation_mode="basic", verification_notice=NOTICE, basic_fallback_id=permit.id,
        )
        return await persist_generated_game(db, user_id=user_id, generated=result)
