"""SQLAlchemy ORM models.

Table: episodes – one row per decision cycle (RL episode step)
Table: kpi      – aggregated performance metrics
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Episode(Base):
    """Records each (state, action, reward) tuple for RL training / audit."""

    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reward: Mapped[float] = mapped_column(Float, nullable=False)

    def __repr__(self) -> str:
        return f"<Episode id={self.id[:8]} reward={self.reward:.4f}>"


class KPI(Base):
    """Aggregated KPI snapshot written after each dispatch cycle."""

    __tablename__ = "kpi"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    cost_saving: Mapped[float] = mapped_column(Float, default=0.0)
    ess_profit: Mapped[float] = mapped_column(Float, default=0.0)
    roi: Mapped[float] = mapped_column(Float, default=0.0)

    def __repr__(self) -> str:
        return (
            f"<KPI id={self.id[:8]} "
            f"cost_saving={self.cost_saving:.2f} "
            f"ess_profit={self.ess_profit:.2f}>"
        )
