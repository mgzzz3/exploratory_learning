import os
from pathlib import Path
import subprocess
import sys
import tomllib


def test_container_defaults_to_grounded_dependencies_with_explicit_legacy_opt_out():
    dockerfile = (Path(__file__).resolve().parents[1] / 'Dockerfile').read_text()
    assert 'ARG INSTALL_RESEARCH=true' in dockerfile
    assert '.[research]' in dockerfile
    assert '"${INSTALL_RESEARCH}" = "false"' in dockerfile


def test_mysql_auth_crypto_dependency_is_declared() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("cryptography") for dependency in dependencies)


def test_official_langchain_research_dependencies_are_declared() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    research_dependencies = pyproject["project"]["optional-dependencies"]["research"]

    assert not any(dependency.startswith("langchain") for dependency in dependencies)
    assert any(dependency.startswith("langchain>=") for dependency in research_dependencies)
    assert any(
        dependency.startswith("langchain-core") for dependency in research_dependencies
    )
    assert any(
        dependency.startswith("langchain-deepseek")
        for dependency in research_dependencies
    )
    assert any(
        dependency.startswith("langchain-tavily")
        for dependency in research_dependencies
    )


def test_official_research_classes_are_importable() -> None:
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy
    from langchain_deepseek import ChatDeepSeek
    from langchain_tavily import TavilyExtract, TavilySearch

    assert callable(create_agent)
    assert ToolStrategy is not None
    assert ChatDeepSeek is not None
    assert TavilySearch is not None
    assert TavilyExtract is not None


def test_legacy_app_runs_without_importing_research_packages() -> None:
    script = r'''
import asyncio
import importlib.abc
import sys


class BlockResearchPackages(importlib.abc.MetaPathFinder):
    blocked = {
        "langchain",
        "langchain_core",
        "langchain_deepseek",
        "langchain_tavily",
    }

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in self.blocked:
            raise ModuleNotFoundError(f"blocked optional research package: {fullname}")
        return None


sys.meta_path.insert(0, BlockResearchPackages())

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.clients.ai import LocalContentGenerator
from app.clients.wechat import LocalWechatClient
from app.core.config import Settings
from app.db.base import Base
from app.main import create_app


async def main():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        _env_file=None,
        environment="test",
        question_generation_mode="legacy",
        use_mock_services=True,
        database_url="sqlite+aiosqlite://",
        jwt_secret="isolated-legacy-test-secret-32-chars",
    )
    app = create_app(
        settings=settings,
        engine=engine,
        wechat_client=LocalWechatClient(),
        content_generator=LocalContentGenerator(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        login = await client.post("/api/v1/auth/wechat", json={"code": "legacy"})
        token = login.json()["access_token"]
        response = await client.post(
            "/api/v1/games",
            headers={"Authorization": f"Bearer {token}"},
            json={"topic": "Python 基础"},
        )
        assert response.status_code == 201, response.text
    await engine.dispose()


asyncio.run(main())
'''
    env = os.environ.copy()
    for name in (
        "TAVILY_API_KEY",
        "DEEPSEEK_API",
        "DEEPSEEK_API_KEY",
        "WECHAT_APP_SECRET",
        "WX_APP_SECRET",
    ):
        env.pop(name, None)
    env.update(
        {
            "QUESTION_GENERATION_MODE": "legacy",
            "USE_MOCK_SERVICES": "true",
            "ENVIRONMENT": "test",
        }
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
