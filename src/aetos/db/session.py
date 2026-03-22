"""Async SQLAlchemy session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import settings
from .models import Base

# Register dataset bundle tables on the same metadata.
from . import models_dataset  # noqa: F401

try:
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
except ModuleNotFoundError:
    engine = None
    AsyncSessionLocal = None

# Idempotent ALTERs for deployments created before new columns / FK existed.
_PG_UPGRADE_SQL = (
    "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS step_events JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS messages JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS reward_decomposition JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS source VARCHAR(32) NOT NULL DEFAULT 'api'",
    "ALTER TABLE kpi ADD COLUMN IF NOT EXISTS episode_id VARCHAR",
)


async def upgrade_schema() -> None:
    """Apply additive schema changes on PostgreSQL (no-op for other backends)."""
    if engine is None:
        return
    if engine.dialect.name != "postgresql":
        return
    async with engine.begin() as conn:
        for stmt in _PG_UPGRADE_SQL:
            await conn.execute(text(stmt))


async def init_db() -> None:
    """Create all tables if they don't exist, then apply additive upgrades."""
    if engine is None:
        raise RuntimeError("database driver unavailable")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await upgrade_schema()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session and commits on success."""
    if AsyncSessionLocal is None:
        raise RuntimeError("database driver unavailable")
    async with AsyncSessionLocal() as session:
        yield session
