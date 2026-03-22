"""ORM tables for imported real-world bundles (ELIA / IEEE-style ``real.pkl``).

Registered on the same :class:`aetos.db.models.Base` as ``episodes`` / ``kpi``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Dataset(Base):
    """One imported bundle (metadata + child tables)."""

    __tablename__ = "dataset"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time_resolution_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    # SQL column name "metadata" — avoid clashing with SQLAlchemy MetaData
    bundle_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)


class DatasetProsumer(Base):
    __tablename__ = "dataset_prosumers"
    __table_args__ = (
        UniqueConstraint("dataset_id", "bus", name="uq_dataset_prosumer_bus"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset.id", ondelete="CASCADE"), index=True
    )
    bus: Mapped[int] = mapped_column(Integer, nullable=False)
    prosumer_type: Mapped[str] = mapped_column(Text, nullable=False)
    has_cdg: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_wt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_pv: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_bess: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_cl: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pv_kw_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wt_kw_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    bess_kwh_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    bess_kw_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cl_kw_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cdg_kw_cap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    load_scale: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)


class DatasetTimeseries(Base):
    __tablename__ = "dataset_timeseries"
    __table_args__ = (
        Index("ix_dataset_ts_dataset_bus_ts", "dataset_id", "bus", "timestamp"),
        Index("ix_dataset_ts_dataset_split", "dataset_id", "split"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset.id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bus: Mapped[int] = mapped_column(Integer, nullable=False)
    prosumer_type: Mapped[str] = mapped_column(Text, nullable=False)
    load_kw: Mapped[float] = mapped_column(Float, nullable=False)
    pv_kw: Mapped[float] = mapped_column(Float, nullable=False)
    wt_kw: Mapped[float] = mapped_column(Float, nullable=False)
    bess_soc_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    bess_ref_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    controllable_load_kw: Mapped[float] = mapped_column(Float, nullable=False)
    cdg_kw_cap: Mapped[float] = mapped_column(Float, nullable=False)
    price_buy: Mapped[float] = mapped_column(Float, nullable=False)
    price_sell: Mapped[float] = mapped_column(Float, nullable=False)
    price_p2p: Mapped[float] = mapped_column(Float, nullable=False)
    split: Mapped[str] = mapped_column(Text, nullable=False, default="train")


class DatasetEliaRaw(Base):
    __tablename__ = "dataset_elia_raw"
    __table_args__ = (Index("ix_dataset_elia_raw_ds_ts", "dataset_id", "timestamp"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset.id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    afrr_up_mw: Mapped[float] = mapped_column(Float, nullable=False)
    mfrr_sa_up_mw: Mapped[float] = mapped_column(Float, nullable=False)
    mfrr_da_up_mw: Mapped[float] = mapped_column(Float, nullable=False)
    afrr_down_mw: Mapped[float] = mapped_column(Float, nullable=False)
    mfrr_sa_down_mw: Mapped[float] = mapped_column(Float, nullable=False)
    mfrr_da_down_mw: Mapped[float] = mapped_column(Float, nullable=False)


class DatasetEliaInternal(Base):
    __tablename__ = "dataset_elia_internal"
    __table_args__ = (Index("ix_dataset_elia_int_ds_ts", "dataset_id", "timestamp"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset.id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    solar_proxy: Mapped[float] = mapped_column(Float, nullable=False)
    wind_proxy: Mapped[float] = mapped_column(Float, nullable=False)
    load_proxy: Mapped[float] = mapped_column(Float, nullable=False)
    price_buy: Mapped[float] = mapped_column(Float, nullable=False)
    price_sell: Mapped[float] = mapped_column(Float, nullable=False)


class DatasetGridBus(Base):
    __tablename__ = "dataset_grid_buses"
    __table_args__ = (
        UniqueConstraint("dataset_id", "bus_id", name="uq_dataset_grid_bus"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset.id", ondelete="CASCADE"), index=True
    )
    bus_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bus_type: Mapped[int] = mapped_column("type", Integer, nullable=False)
    pd_mw: Mapped[float] = mapped_column(Float, nullable=False)
    qd_mvar: Mapped[float] = mapped_column(Float, nullable=False)
    base_kv: Mapped[float] = mapped_column(Float, nullable=False)
    vm: Mapped[float] = mapped_column(Float, nullable=False)
    va: Mapped[float] = mapped_column(Float, nullable=False)
    vmin: Mapped[float] = mapped_column(Float, nullable=False)
    vmax: Mapped[float] = mapped_column(Float, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")


class DatasetGridBranch(Base):
    __tablename__ = "dataset_grid_branches"
    __table_args__ = (
        UniqueConstraint("dataset_id", "from_bus", "to_bus", name="uq_dataset_grid_branch"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset.id", ondelete="CASCADE"), index=True
    )
    from_bus: Mapped[int] = mapped_column(Integer, nullable=False)
    to_bus: Mapped[int] = mapped_column(Integer, nullable=False)
    r: Mapped[float] = mapped_column(Float, nullable=False)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    b: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)


class DatasetGridGenerator(Base):
    __tablename__ = "dataset_grid_generators"
    __table_args__ = (UniqueConstraint("dataset_id", "bus", name="uq_dataset_grid_gen_bus"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dataset.id", ondelete="CASCADE"), index=True
    )
    bus: Mapped[int] = mapped_column(Integer, nullable=False)
    pg: Mapped[float] = mapped_column(Float, nullable=False)
    qg: Mapped[float] = mapped_column(Float, nullable=False)
    p_max: Mapped[float] = mapped_column(Float, nullable=False)
    p_min: Mapped[float] = mapped_column(Float, nullable=False)
    q_max: Mapped[float] = mapped_column(Float, nullable=False)
    q_min: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
