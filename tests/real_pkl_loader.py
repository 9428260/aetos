"""Load ``tests/data/real.pkl`` and map slices to :class:`aetos.state.EnergyState`.

The pickle is a dict (ELIA / IEEE-style reproduction dataset, 15-minute resolution).
Requires **Python 3.11–3.12** and **pandas**; Python 3.14 may fail to unpickle
timezone-aware pandas arrays (known compatibility issue).

See ``metadata['warning']`` inside the file for interpretation caveats.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

REAL_PKL_PATH = Path(__file__).resolve().parent / "data" / "real.pkl"


def load_real_bundle(path: Path | None = None) -> dict[str, Any]:
    """Load the full bundle (metadata, timeseries, grid, prosumers, …)."""
    p = path or REAL_PKL_PATH
    with open(p, "rb") as f:
        return pickle.load(f)


def _prosumer_row(bundle: dict, bus: int):
    pr = bundle["prosumers"]
    row = pr.loc[pr["bus"] == bus]
    if row.empty:
        raise ValueError(f"no prosumer for bus={bus}")
    return row.iloc[0]


def timeseries_slice_to_energy_state(
    bundle: dict,
    *,
    bus: int = 48,
    day_offset: int = 0,
) -> "EnergyState":
    """Build a 24-point :class:`EnergyState` from one bus and one calendar day.

    - ``price``: hourly mean of ``price_buy`` ÷ 1000 (treats values ~€/MWh as €/kWh scale).
    - ``load`` / ``generation``: hourly mean of ``load_kw`` and ``pv_kw`` + ``wt_kw``.
    - ``ess_soc``: last interval's ``bess_soc_kwh`` / ``bess_kwh_cap`` for that bus.
    """
    import pandas as pd

    from aetos.state import Constraints, EnergyState

    row = _prosumer_row(bundle, bus)
    cap_kwh = float(row["bess_kwh_cap"] or 1.0)
    export_cap = float(row.get("cdg_kw_cap", 50.0) or 50.0)

    ts = bundle["timeseries"]
    ts = ts.loc[ts["bus"] == bus, :].copy()
    if ts.empty:
        raise ValueError(f"no timeseries rows for bus={bus}")
    ts = ts.set_index("timestamp").sort_index()
    # First full local day (UTC timestamps)
    day0 = ts.index.min().normalize() + pd.Timedelta(days=day_offset)
    day1 = day0 + pd.Timedelta(days=1)
    day = ts.loc[day0:day1 - pd.Timedelta(seconds=1)]
    if day.empty:
        raise ValueError(f"no data for day_offset={day_offset}")

    hourly = day.resample("h").agg(
        {
            "load_kw": "mean",
            "pv_kw": "mean",
            "wt_kw": "mean",
            "price_buy": "mean",
            "bess_soc_kwh": "last",
        }
    )
    # Ensure 24 hours; pad or trim
    vals = hourly.head(24)
    n = len(vals)
    if n < 24:
        # repeat last row to pad (test-only)
        pad = 24 - n
        last = vals.iloc[[-1] * pad]
        vals = pd.concat([vals, last], ignore_index=True)
    elif n > 24:
        vals = vals.iloc[:24]

    price = [round(float(x) / 1000.0, 6) for x in vals["price_buy"]]
    load = [round(float(x), 4) for x in vals["load_kw"]]
    gen = [round(float(pv) + float(wt), 4) for pv, wt in zip(vals["pv_kw"], vals["wt_kw"])]
    soc_kwh = float(vals["bess_soc_kwh"].iloc[-1])
    ess_soc = max(0.0, min(1.0, soc_kwh / cap_kwh))

    t0 = vals.index[0]
    return EnergyState(
        price=price,
        load=load,
        generation=gen,
        ess_soc=round(ess_soc, 4),
        constraints=Constraints(export_limit=export_cap, soc_min=0.1, soc_max=0.9),
        timestamp=t0.isoformat() if hasattr(t0, "isoformat") else str(t0),
    )


def energy_state_json_roundtrip(state: "EnergyState") -> bool:
    """Return True if state is JSON-serialisable like PostgreSQL JSONB expects."""
    payload = state.model_dump()
    json.dumps(payload)
    return True
