"""Create the schema in the configured database.

Run: .venv/bin/python -m app.bootstrap

create_all only ADDS missing tables — it never ALTERs existing
ones. After a model change, reset the dev database (drop/recreate,
e.g. dropdb knowaplan && createdb knowaplan) and re-run this.
Real migrations (Alembic) arrive with live dogfood, when data must
survive schema changes (decisions.md 2026-07-16).
"""
import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import get_engine
from app.models import Base


async def create_tables(engine: AsyncEngine | None = None) -> None:
    """create_all against the given engine (default: the configured
    database). Idempotent — existing tables are left untouched."""
    engine = engine or get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _main() -> None:
    await create_tables()
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(_main())
    print("schema ready (existing tables untouched)")
