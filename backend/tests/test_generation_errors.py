from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.clients.ai import ContentGenerationError, DeepSeekContentGenerator
from app.clients.tavily import TavilyAuthenticationError, TavilyRateLimitError, TavilyUnavailableError, PageUnreadableError
from app.core.generation_budget import GenerationDeadlineError
from app.main import create_app
from app.services.grounded_generation import GroundingValidationError
from app.services.research_agent import ResearchAgentFailedError
from app.services.research_acceptance import ResearchAcceptanceError

from .conftest import login
from .test_grounded_persistence import FailingStrategy
from .test_game_generation_pipeline import row_counts
from .test_grounded_generation import research_context, grounded_game


@pytest.mark.anyio
@pytest.mark.parametrize("failure,status,code,reason", [
    (TavilyAuthenticationError("private-provider-content"), 503, "SEARCH_UNAVAILABLE", "PROVIDER_AUTH_FAILED"),
    (TavilyRateLimitError("private-provider-content"), 503, "SEARCH_UNAVAILABLE", "PROVIDER_RATE_LIMITED"),
    (TavilyUnavailableError("private-provider-content", reason="PROVIDER_TIMEOUT"), 503, "SEARCH_UNAVAILABLE", "PROVIDER_TIMEOUT"),
    (PageUnreadableError("private-provider-content", reason="PAGE_TOO_LARGE"), 422, "PAGE_UNREADABLE", "PAGE_TOO_LARGE"),
    (ResearchAgentFailedError("private-provider-content", reason="MODEL_BUDGET_EXHAUSTED"), 502, "RESEARCH_AGENT_FAILED", "MODEL_BUDGET_EXHAUSTED"),
    (GenerationDeadlineError("research"), 502, "RESEARCH_AGENT_FAILED", "RESEARCH_TIMEOUT"),
    (GenerationDeadlineError("generation"), 502, "AI_GENERATION_FAILED", "GENERATION_TIMEOUT"),
    (GenerationDeadlineError("validation"), 502, "AI_GENERATION_FAILED", "VALIDATION_TIMEOUT"),
    (ContentGenerationError("private-provider-content"), 502, "AI_GENERATION_FAILED", "GENERATION_UNAVAILABLE"),
    (GroundingValidationError("private-provider-content"), 502, "GROUNDING_VALIDATION_FAILED", "UNSUPPORTED_FACTS"),
    (ResearchAcceptanceError(code="SOURCES_INSUFFICIENT", message="private-provider-content", details={"reason": "sources_conflict"}), 422, "SOURCES_INSUFFICIENT", "CONFLICTING_EVIDENCE"),
    (ResearchAcceptanceError(code="TOPIC_AMBIGUOUS", message="private-provider-content", details={"interpretations": ["含义一", "含义二"]}), 422, "TOPIC_AMBIGUOUS", "AMBIGUOUS_TOPIC"),
])
async def test_errors_keep_category_safe_reason_random_request_id_and_no_partial_game(engine, settings, wechat, generator, failure, status, code, reason):
    app = create_app(settings=settings, engine=engine, wechat_client=wechat, content_generator=generator, generation_strategy=FailingStrategy(failure))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = await login(client)
        ids = []
        for _ in range(2):
            response = await client.post("/api/v1/games", json={"topic": "private-topic"}, headers={**headers, "X-Request-ID": "untrusted-id"})
            assert response.status_code == status
            error = response.json()["error"]
            assert error["code"] == code
            assert error["details"]["reason"] == reason
            ids.append(error["details"]["request_id"])
            assert error["details"]["fallback"] == {"available": False}
            assert "private-" not in response.text
            if code == "TOPIC_AMBIGUOUS":
                assert error["details"]["interpretations"] == ["含义一", "含义二"]
        assert ids[0] != ids[1] and all(len(item) == 32 for item in ids)
    async with async_sessionmaker(engine)() as db:
        assert await row_counts(db) == (0, 0)
    assert generator.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["generation", "validation"])
async def test_sdk_timeout_and_bad_output_are_typed_not_reported_as_fact_failure(stage):
    from types import SimpleNamespace
    generator = DeepSeekContentGenerator(api_key="offline", base_url="https://example.com", model="configured", max_retries=3)
    root = generator.client
    class Responses:
        async def create(self, **kwargs):
            raise httpx.ReadTimeout("private-provider-content")
    fake = SimpleNamespace(responses=Responses())
    fake.with_options = lambda **kwargs: fake
    generator.client = fake
    with pytest.raises(ContentGenerationError) as caught:
        if stage == "generation":
            await generator.generate_grounded(research_context(), [])
        else:
            await generator.validate_grounding(research_context(), grounded_game())
    assert caught.value.reason == f"{stage.upper()}_TIMEOUT"
    assert caught.value.__cause__ is None
    await root.close()


@pytest.mark.anyio
async def test_http_disconnect_cancels_and_joins_inflight_generation_without_save(engine, settings, wechat, generator):
    started, cancelled = asyncio.Event(), asyncio.Event()
    class WaitingStrategy:
        async def generate(self, descriptor):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    app = create_app(settings=settings, engine=engine, wechat_client=wechat, content_generator=generator, generation_strategy=WaitingStrategy())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = await login(client)
    queue = asyncio.Queue()
    await queue.put({"type": "http.request", "body": json.dumps({"topic": "高情商聊天"}).encode(), "more_body": False})
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/api/v1/games", "raw_path": b"/api/v1/games", "query_string": b"", "root_path": "", "headers": [(b"content-type", b"application/json"), (b"authorization", headers["Authorization"].encode())], "client": ("127.0.0.1", 1), "server": ("test", 80)}
    sent = []
    async def send(message):
        sent.append(message)
    task = asyncio.create_task(app(scope, queue.get, send))
    try:
        await asyncio.wait_for(started.wait(), 1)
        await queue.put({"type": "http.disconnect"})
        await asyncio.sleep(0.03)
        assert task.done(), "HTTP disconnect must stop the running operation"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert not any(item.get("status") == 201 for item in sent)
        async with async_sessionmaker(engine)() as db:
            assert await row_counts(db) == (0, 0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
