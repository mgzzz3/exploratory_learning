"""Local-only UI fault harness; never imported by app or deployment entrypoints.

ALLOW_UI_FIXTURES=1 USE_MOCK_SERVICES=true .venv/bin/uvicorn tests.ui_preview:app --host 127.0.0.1 --port 8878 --no-access-log
All provider/WeChat calls are fake, with an in-memory throwaway database.
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.clients.ai import ContentGenerationError, LocalContentGenerator
from app.core.config import Settings
from app.core.errors import AppError
from app.db.base import Base
from app.db.models import LearningSession
from app.main import create_app
from app.services.generation_strategy import GroundedGenerationStrategy, LocalResearcher
from app.services.generation_errors import CONTRACTS
from tests.fakes import FakeWechatClient, generated_game

if os.environ.get("ALLOW_UI_FIXTURES") != "1":
    raise RuntimeError("UI fixture server requires explicit local opt-in")

class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = "RESEARCH_AGENT_FAILED"
    basic_fails: bool = False
    delay_seconds: float = Field(default=0.3, ge=0, le=10)

scenario = Scenario()
counts = {"online": 0, "basic": 0, "cancelled": 0}
wechat = FakeWechatClient()

class FixtureGenerator:
    async def generate(self, topic):
        counts["basic"] += 1
        await asyncio.sleep(scenario.delay_seconds)
        if scenario.basic_fails:
            raise ContentGenerationError("fixture generation failure")
        return generated_game(topic)

class FixtureStrategy:
    async def generate(self, descriptor):
        counts["online"] += 1
        try:
            await asyncio.sleep(scenario.delay_seconds)
            if scenario.code != "SUCCESS":
                status, message, reason = CONTRACTS[scenario.code]
                failure = AppError(status_code=status, code=scenario.code, message=message,
                    details={"interpretations": ["方向一", "方向二"]} if scenario.code == "TOPIC_AMBIGUOUS" else None)
                failure.reason = reason
                raise failure
            local = LocalContentGenerator()
            return await GroundedGenerationStrategy(researcher=LocalResearcher(), generator=local, validator=local).generate(descriptor)
        except asyncio.CancelledError:
            counts["cancelled"] += 1
            raise

engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
settings = Settings(_env_file=None, environment="test", use_mock_services=True,
    question_generation_mode="grounded", database_url="sqlite+aiosqlite://",
    jwt_secret="ui-fixture-only-not-for-production-0001")
app = create_app(settings=settings, engine=engine, wechat_client=wechat,
    content_generator=FixtureGenerator(), generation_strategy=FixtureStrategy())

@asynccontextmanager
async def lifespan(_):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app.router.lifespan_context = lifespan

@app.post("/__qa/scenario")
async def change_scenario(value: Scenario):
    global scenario
    if value.code not in CONTRACTS and value.code != "SUCCESS":
        raise HTTPException(422, "unknown fixture")
    scenario = value
    return {"configured": True}

@app.get("/__qa/status")
async def qa_status():
    async with app.state.session_factory() as db:
        games = await db.scalar(select(func.count()).select_from(LearningSession))
    return {**counts, "games": games, "safety_checks": len(wechat.safety_calls)}
