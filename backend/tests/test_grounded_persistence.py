from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.models import LearningSession, Level
from app.main import create_app
from app.schemas.learning_input import InputDescriptor
from app.services.generation_strategy import GenerationResult
from app.services.generation_strategy import LegacyGenerationStrategy

from .conftest import login
from .fakes import FakeContentGenerator, FakeWechatClient
from .test_generation_strategy import grounded_result


@dataclass
class StaticStrategy:
    result: GenerationResult

    async def generate(self, descriptor: InputDescriptor) -> GenerationResult:
        del descriptor
        return self.result


async def grounded_client(engine, result: GenerationResult) -> AsyncClient:
    settings = Settings(
        _env_file=None,
        environment="test",
        question_generation_mode="legacy",
        use_mock_services=True,
        database_url="sqlite+aiosqlite://",
        jwt_secret="grounded-persistence-test-secret-123456",
    )
    app = create_app(
        settings=settings,
        engine=engine,
        wechat_client=FakeWechatClient(),
        content_generator=FakeContentGenerator(),
        generation_strategy=StaticStrategy(result),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.anyio
async def test_grounded_create_and_get_persist_identical_source_metadata(engine) -> None:
    expected = grounded_result()
    async with await grounded_client(engine, expected) as client:
        headers = await login(client)
        created = await client.post(
            "/api/v1/games",
            headers=headers,
            json={"topic": "Harness Engineering"},
        )
        assert created.status_code == 201, created.text
        detail = await client.get(
            f"/api/v1/games/{created.json()['id']}",
            headers=headers,
        )

    payload = created.json()
    assert detail.json() == payload
    assert payload["input_type"] == "keyword"
    assert payload["retrieved_at"] == expected.retrieved_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert payload["sources"] == [
        source.model_dump(mode="json") for source in expected.sources
    ]

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        row = await db.scalar(select(LearningSession))
        levels = list(
            (
                await db.scalars(
                    select(Level).order_by(Level.position)
                )
            ).all()
        )
    assert row is not None
    assert row.source_input == "Harness Engineering"
    assert row.input_type == "keyword"
    assert row.sources == [source.model_dump(mode="json") for source in expected.sources]
    assert [level.source_ids for level in levels] == expected.level_source_ids


@pytest.mark.anyio
async def test_legacy_and_pre_migration_defaults_are_explicitly_ungrounded(
    client: AsyncClient,
) -> None:
    headers = await login(client)
    created = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "Python 基础"},
    )

    assert created.status_code == 201
    assert created.json()["input_type"] == "keyword"
    assert created.json()["retrieved_at"] is None
    assert created.json()["sources"] == []


@pytest.mark.anyio
async def test_real_legacy_strategy_rejects_url_at_api_boundary(engine) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        question_generation_mode="legacy",
        use_mock_services=True,
        database_url="sqlite+aiosqlite://",
        jwt_secret="legacy-url-test-secret-123456789012",
    )
    generator = FakeContentGenerator()
    app = create_app(
        settings=settings,
        engine=engine,
        wechat_client=FakeWechatClient(),
        content_generator=generator,
        generation_strategy=LegacyGenerationStrategy(generator),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        headers = await login(client)
        response = await client.post(
            "/api/v1/games",
            headers=headers,
            json={"topic": "https://docs.example.com/current"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "URL_REQUIRES_RESEARCH"
    assert generator.calls == []


class PipelineFailure(RuntimeError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details


@dataclass
class FailingStrategy:
    error: Exception

    async def generate(self, descriptor: InputDescriptor) -> GenerationResult:
        del descriptor
        raise self.error


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("INVALID_SOURCE_URL", 422),
        ("PAGE_UNREADABLE", 422),
        ("TOPIC_AMBIGUOUS", 422),
        ("SOURCES_INSUFFICIENT", 422),
        ("RESEARCH_AGENT_FAILED", 502),
        ("GROUNDING_VALIDATION_FAILED", 502),
        ("SEARCH_UNAVAILABLE", 503),
        ("URL_REQUIRES_RESEARCH", 422),
    ],
)
async def test_generation_errors_are_stable_and_leave_no_partial_games(
    engine,
    code: str,
    status: int,
) -> None:
    expected = grounded_result()
    details = {"interpretations": ["含义一", "含义二"]} if code == "TOPIC_AMBIGUOUS" else None
    settings = Settings(
        _env_file=None,
        environment="test",
        question_generation_mode="legacy",
        use_mock_services=True,
        database_url="sqlite+aiosqlite://",
        jwt_secret="grounded-errors-test-secret-123456789",
    )
    app = create_app(
        settings=settings,
        engine=engine,
        wechat_client=FakeWechatClient(),
        content_generator=FakeContentGenerator(),
        generation_strategy=FailingStrategy(PipelineFailure(code, details)),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        headers = await login(client)
        response = await client.post(
            "/api/v1/games",
            headers=headers,
            json={"topic": "Harness Engineering"},
        )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    if details:
        assert response.json()["error"]["details"]["interpretations"] == details["interpretations"]
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        count = await db.scalar(select(func.count()).select_from(LearningSession))
    assert count == 0
