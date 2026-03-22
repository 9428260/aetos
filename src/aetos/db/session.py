"""Async SQLAlchemy session factory."""

from collections.abc import AsyncGenerator
import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import settings
from .models import Base

# Register dataset bundle tables on the same metadata.
from . import models_dataset  # noqa: F401

logger = logging.getLogger(__name__)

try:
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    # asyncpg requires pgvector's custom codec to be registered on every new
    # connection so it can serialise/deserialise the `vector` type correctly.
    @event.listens_for(engine.sync_engine, "connect")
    def _register_vector_codec(dbapi_connection, _connection_record):
        from pgvector.asyncpg import register_vector

        try:
            if hasattr(dbapi_connection, "run_async"):
                dbapi_connection.run_async(register_vector)
                return
            if hasattr(dbapi_connection, "run_sync"):
                dbapi_connection.run_sync(register_vector)
                return
            register_vector(dbapi_connection)
        except ValueError as exc:
            if "unknown type: public.vector" not in str(exc):
                raise
            logger.debug("pgvector type not available yet; skipping codec registration")

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
    "ALTER TABLE strategy_memory ADD COLUMN IF NOT EXISTS embedding_schema VARCHAR(32)",
    "CREATE INDEX IF NOT EXISTS ix_strategy_memory_embedding_schema ON strategy_memory (embedding_schema)",
)

# pgvector migration: convert existing JSONB embedding column to native vector type
# and build an HNSW index for fast approximate nearest-neighbour search.
_VECTOR_DIM = settings.vector_embedding_dim
_PG_VECTOR_UPGRADE_SQL = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    # Drop the old JSONB column and re-create as vector (only when type differs).
    f"""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'strategy_memory'
              AND column_name = 'embedding'
              AND data_type = 'jsonb'
        ) THEN
            ALTER TABLE strategy_memory DROP COLUMN embedding;
            ALTER TABLE strategy_memory ADD COLUMN embedding vector({_VECTOR_DIM});
        END IF;
    END $$
    """,
    # Add the column if it is missing entirely (fresh installs after the model change).
    f"ALTER TABLE strategy_memory ADD COLUMN IF NOT EXISTS embedding vector({_VECTOR_DIM})",
    # HNSW index for cosine-distance ANN search (works well even on small datasets).
    f"""
    CREATE INDEX IF NOT EXISTS strategy_memory_embedding_hnsw
        ON strategy_memory
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """,
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
        for stmt in _PG_VECTOR_UPGRADE_SQL:
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
