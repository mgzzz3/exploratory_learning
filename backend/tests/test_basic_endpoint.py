from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.clients.ai import ContentGenerationError
from app.main import create_app
from app.services.generation_strategy import LegacyGenerationStrategy
from .conftest import login
from .test_grounded_persistence import FailingStrategy, StaticStrategy
from .test_generation_strategy import grounded_result
from .test_game_generation_pipeline import add_user, row_counts


def make_app(settings, engine, wechat, generator):
    settings = settings.model_copy(update={"question_generation_mode": "grounded", "use_mock_services": True})
    return create_app(settings=settings, engine=engine, wechat_client=wechat, content_generator=generator, generation_strategy=FailingStrategy(ContentGenerationError("offline")))


async def failed_request(client, headers, topic="高情商聊天"):
    response = await client.post("/api/v1/games", headers=headers, json={"topic": topic})
    assert response.status_code == 502
    return response.json()["error"]["details"]


@pytest.mark.anyio
async def test_explicit_basic_request_only_after_failure_then_replay_and_reopen(engine, settings, wechat, generator):
    app = make_app(settings, engine, wechat, generator)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = await login(client)
        original = await failed_request(client, headers)
        assert original["fallback"]["available"]
        assert generator.calls == []
        async with async_sessionmaker(engine)() as db:
            assert await row_counts(db) == (0, 0)
        request = {"topic": "高情商聊天", "fallback_token": original["fallback"]["token"], "acknowledge_unverified": True}
        response = await client.post("/api/v1/games/basic", headers=headers, json=request)
        assert response.status_code == 201, response.text
        game = response.json()
        assert game["generation_mode"] == "basic"
        assert game["verification_notice"] == "未经联网核验"
        assert game["sources"] == [] and game["retrieved_at"] is None
        assert generator.calls == ["高情商聊天"]
        repeated = await client.post("/api/v1/games/basic", headers=headers, json=request)
        assert repeated.status_code == 201 and repeated.json() == game
        assert generator.calls == ["高情商聊天"]
        app.state.settings.question_generation_mode = "legacy"
        detail = await client.get(f"/api/v1/games/{game['id']}", headers=headers)
        assert detail.json() == game
        refused = await client.post("/api/v1/games/basic", headers=headers, json=request)
        assert refused.status_code == 403
        app.state.generation_strategy = LegacyGenerationStrategy(generator)
        legacy = await client.post("/api/v1/games", headers=headers, json={"topic": "旧版主题"})
        assert legacy.json()["generation_mode"] == "legacy"
        app.state.settings.question_generation_mode = "grounded"
        app.state.generation_strategy = StaticStrategy(grounded_result())
        grounded = await client.post("/api/v1/games", headers=headers, json={"topic": "Harness Engineering"})
        assert grounded.json()["generation_mode"] == "grounded"
        for _ in range(3):
            answered = await client.post(f"/api/v1/games/{game['id']}/answers", headers=headers, json={"option": 0, "attempt_id": str(uuid4())})
            assert answered.json()["game"]["verification_notice"] == "未经联网核验"


@pytest.mark.anyio
@pytest.mark.parametrize("case,status", [("no_auth",401), ("wrong_user",403), ("no_token",422), ("bad_token",403), ("no_consent",422), ("false",422), ("string",422), ("integer",422), ("extra",422), ("url",422), ("long",422), ("changed_topic",403), ("new_version",403)])
async def test_basic_rejects_before_generation(engine, settings, wechat, generator, case, status):
    app = make_app(settings, engine, wechat, generator)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = await login(client)
        original = await failed_request(client, headers)
        data = {"topic": "高情商聊天", "fallback_token": original["fallback"]["token"], "acknowledge_unverified": True}
        if case == "no_auth": headers = {}
        elif case == "wrong_user": headers = await login(client, "another-user")
        elif case == "no_token": data.pop("fallback_token")
        elif case == "bad_token": data["fallback_token"] = "invalid"
        elif case == "no_consent": data.pop("acknowledge_unverified")
        elif case in {"false", "string", "integer"}: data["acknowledge_unverified"] = {"false":False, "string":"true", "integer":1}[case]
        elif case == "extra": data["mode"] = "basic"
        elif case == "url": data["topic"] = "https://example.com"
        elif case == "long": data["topic"] = "x" * 81
        elif case == "changed_topic": data["topic"] = "Python 基础"
        elif case == "new_version": data["topic"] = "高情商聊天 2026最新版"
        response = await client.post("/api/v1/games/basic", headers=headers, json=data)
        assert response.status_code == status, response.text
        assert generator.calls == []
        async with async_sessionmaker(engine)() as db:
            assert await row_counts(db) == (0, 0)


@pytest.mark.anyio
@pytest.mark.parametrize("case,status,code", [("blocked",422,"CONTENT_BLOCKED"), ("safety_error",503,"WECHAT_UNAVAILABLE"), ("invalid_output",502,"AI_GENERATION_FAILED"), ("generation_error",502,"AI_GENERATION_FAILED")])
async def test_basic_rechecks_safety_and_does_not_recursively_offer_fallback(engine, settings, wechat, generator, case, status, code):
    from app.clients.wechat import WechatClientError
    app = make_app(settings, engine, wechat, generator)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = await login(client)
        original = await failed_request(client, headers)
        async def check(*args):
            if case == "safety_error": raise WechatClientError("private")
            return case != "blocked"
        wechat.check_message = check
        async def generate(topic):
            generator.calls.append(topic)
            if case == "generation_error": raise ContentGenerationError("private")
            return {"title": "不完整"}
        generator.generate = generate
        response = await client.post("/api/v1/games/basic", headers=headers, json={"topic":"高情商聊天", "fallback_token":original["fallback"]["token"], "acknowledge_unverified":True})
        assert response.status_code == status
        error = response.json()["error"]
        assert error["code"] == code
        assert error["details"]["fallback"] == {"available":False}
        assert error["details"]["request_id"] != original["request_id"]
        assert "private" not in response.text
        if case in {"blocked", "safety_error"}: assert not generator.calls
        async with async_sessionmaker(engine)() as db:
            assert await row_counts(db) == (0, 0)


@pytest.mark.anyio
async def test_basic_has_independent_deadline_that_cancels_old_generator(engine, wechat):
    from app.services.basic_knowledge import BasicKnowledgeService
    from app.schemas.game import BasicGameCreateRequest
    from app.services.basic_permits import FallbackPermits
    from app.services.generation_errors import public_generation_error
    from app.core.errors import AppError
    cancelled = asyncio.Event()
    class SlowGenerator:
        async def generate(self, topic):
            try: await asyncio.Event().wait()
            finally: cancelled.set()
    permits = FallbackPermits(secret="offline-basic-secret-at-least-32-characters", mode="grounded")
    service = BasicKnowledgeService(wechat=wechat, generator=SlowGenerator(), permits=permits, timeout_seconds=0.02)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user = await add_user(db)
        fallback = permits.issue(user_id=user.id, topic="高情商聊天", request_id=uuid4().hex, error=public_generation_error(ContentGenerationError("offline")))
        with pytest.raises(AppError) as caught:
            await service.create(db, user=user, payload=BasicGameCreateRequest(topic="高情商聊天", fallback_token=fallback["token"], acknowledge_unverified=True))
        assert caught.value.details["reason"] == "GENERATION_TIMEOUT"
        assert cancelled.is_set()
        assert await row_counts(db) == (0, 0)
