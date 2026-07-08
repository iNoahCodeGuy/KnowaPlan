"""Async database plumbing.

The engine is created lazily so importing the app (tests, tooling)
never requires a running Postgres — only actually touching the DB
does.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url)
        _sessionmaker = async_sessionmaker(
            _engine, expire_on_commit=False
        )
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed after."""
    get_engine()
    if _sessionmaker is None:  # not reachable; assert-free for -O
        raise RuntimeError("engine init did not set sessionmaker")
    async with _sessionmaker() as session:
        yield session
