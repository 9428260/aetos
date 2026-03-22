"""Import ``tests/data/real.pkl`` (or a path) into PostgreSQL dataset tables.

Requires **sync** PostgreSQL driver: ``psycopg`` (see ``[project.optional-dependencies] dev``).

Usage::

    pip install -e ".[dev]"   # pandas + psycopg
    export DATABASE_URL=postgresql+asyncpg://aetos:aetos@localhost:5432/aetos
    python -m aetos.db.import_real_pkl --pickle tests/data/real.pkl

Python **3.11–3.12** recommended; 3.14 may fail to unpickle pandas datetime arrays.
"""

from __future__ import annotations

import argparse
import logging
import pickle
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, delete, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session

from ..config import settings
from . import models_dataset  # noqa: F401 — register ORM tables
from .models import Base
from .models_dataset import Dataset

logger = logging.getLogger(__name__)


def _sync_database_url(async_url: str) -> str:
    u = async_url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    if u == async_url:
        u = async_url.replace("postgresql+asyncpg:", "postgresql+psycopg:")
    return u


def _slugify(name: str, fallback: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())[:120]
    return s or fallback


def import_bundle(
    pickle_path: Path,
    *,
    slug: str | None = None,
    source_uri: str | None = None,
    database_url: str | None = None,
    recreate: bool = False,
    timeseries_chunk: int = 1_000,
) -> uuid.UUID:
    """Load pickle and insert all tables. Returns ``dataset.id``."""
    try:
        import pandas as pd
    except ImportError as e:
        raise SystemExit("pandas is required: pip install pandas") from e

    try:
        import psycopg  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "psycopg is required for bulk load: pip install 'psycopg[binary]'"
        ) from e

    url = _sync_database_url(database_url or settings.database_url)
    engine = create_engine(url, pool_pre_ping=True)

    with open(pickle_path, "rb") as f:
        bundle = pickle.load(f)

    if not isinstance(bundle, dict):
        raise ValueError("pickle root must be a dict")

    meta = bundle.get("metadata") or {}
    name = meta.get("name") or pickle_path.stem
    res_min = int(meta.get("time_resolution_minutes") or 15)
    slug_final = slug or _slugify(name, "dataset_import")

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        existing = session.scalars(select(Dataset).where(Dataset.slug == slug_final)).first()
        if existing is not None:
            if not recreate:
                raise SystemExit(
                    f"Dataset slug {slug_final!r} already exists. "
                    "Use --recreate to delete and re-import."
                )
            session.execute(delete(Dataset).where(Dataset.id == existing.id))
            session.commit()
            logger.info("Removed existing dataset %s", existing.id)

        ds = Dataset(
            slug=slug_final,
            name=str(name)[:2000],
            time_resolution_minutes=res_min,
            bundle_metadata=meta,
            source_uri=source_uri or str(pickle_path.resolve()),
        )
        session.add(ds)
        session.commit()
        did = ds.id
        logger.info("Created dataset id=%s slug=%s", did, slug_final)

    # Child tables via pandas (fast path)
    eng = create_engine(url)

    def add_id(df, table_name: str) -> None:
        d = df.copy()
        if not isinstance(d.index, pd.RangeIndex):
            d = d.reset_index(drop=True)
        # PostgreSQL UUID columns require uuid.UUID, not str (pandas would send VARCHAR).
        d.insert(0, "dataset_id", did)
        if "timestamp" in d.columns:
            d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
        d.to_sql(
            table_name,
            eng,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=min(timeseries_chunk, max(len(d), 1)),
            dtype={"dataset_id": PG_UUID(as_uuid=True)},
        )
        logger.info("Inserted %d rows into %s", len(d), table_name)

    # prosumers
    pr = bundle["prosumers"].copy()
    add_id(pr, "dataset_prosumers")

    # elia
    er = bundle["elia_raw"].copy()
    add_id(er, "dataset_elia_raw")

    ei = bundle["elia_internal"].copy()
    add_id(ei, "dataset_elia_internal")

    # grid
    gb = bundle["grid"]["buses"].copy()
    add_id(gb, "dataset_grid_buses")

    br = bundle["grid"]["branches"].copy()
    add_id(br, "dataset_grid_branches")

    gen = bundle["grid"]["generators"].copy()
    add_id(gen, "dataset_grid_generators")

    # timeseries (large)
    ts = bundle["timeseries"].copy()
    add_id(ts, "dataset_timeseries")

    logger.info("Import complete dataset_id=%s", did)
    return did


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Import real.pkl into PostgreSQL dataset tables.")
    p.add_argument(
        "--pickle",
        type=Path,
        default=Path("tests/data/real.pkl"),
        help="Path to real.pkl",
    )
    p.add_argument("--slug", type=str, default=None, help="Unique slug (default from metadata name)")
    p.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Override DATABASE_URL (sync URL derived automatically)",
    )
    p.add_argument(
        "--recreate",
        action="store_true",
        help="If slug exists, delete that dataset and re-import",
    )
    args = p.parse_args(argv)

    if not args.pickle.is_file():
        logger.error("File not found: %s", args.pickle)
        sys.exit(1)

    try:
        import_bundle(
            args.pickle,
            slug=args.slug,
            database_url=args.database_url,
            recreate=args.recreate,
        )
    except NotImplementedError as e:
        logger.error(
            "Pickle failed to load (try Python 3.12 and matching pandas): %s",
            e,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
