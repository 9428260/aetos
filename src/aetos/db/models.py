"""SQLAlchemy ORM models.

- ``episodes`` — one row per decision cycle (state, action, reward, full workflow trace)
- ``kpi`` — KPI snapshot per episode, linked via ``episode_id``
- ``strategy_memory`` — vectorized strategy/state memories for retrieval (pgvector)
"""

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..config import settings


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Episode(Base):
    """Records each optimisation cycle for audit, replay, and RL-style training."""

    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reward: Mapped[float] = mapped_column(Float, nullable=False)
    step_events: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    messages: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    reward_decomposition: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'api'"), index=True
    )

    kpi: Mapped["KPI | None"] = relationship("KPI", back_populates="episode", uselist=False)

    def __repr__(self) -> str:
        return f"<Episode id={self.id[:8]} reward={self.reward:.4f}>"


class KPI(Base):
    """Aggregated KPI snapshot written together with each episode."""

    __tablename__ = "kpi"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    episode_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    cost_saving: Mapped[float] = mapped_column(Float, default=0.0)
    ess_profit: Mapped[float] = mapped_column(Float, default=0.0)
    roi: Mapped[float] = mapped_column(Float, default=0.0)

    episode: Mapped["Episode | None"] = relationship("Episode", back_populates="kpi")

    def __repr__(self) -> str:
        return (
            f"<KPI id={self.id[:8]} "
            f"cost_saving={self.cost_saving:.2f} "
            f"ess_profit={self.ess_profit:.2f}>"
        )


class StrategyMemory(Base):
    """Vectorized memory entries for strategy retrieval."""

    __tablename__ = "strategy_memory"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    episode_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("episodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    strategy_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'api'"), index=True
    )
    selected: Mapped[bool] = mapped_column(nullable=False, default=False)
    reward: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    state_summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    strategy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reward_decomposition: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    embedding_schema: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    embedding: Mapped[list] = mapped_column(
        Vector(settings.vector_embedding_dim), nullable=False
    )

    def __repr__(self) -> str:
        return f"<StrategyMemory id={self.id[:8]} mode={self.mode} reward={self.reward:.4f}>"
