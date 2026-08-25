from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def build_engine(database_url: str) -> AsyncEngine:
    options: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        options.pop("pool_pre_ping")
    else:
        options.update({"pool_recycle": 1800})
    return create_async_engine(database_url, **options)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
