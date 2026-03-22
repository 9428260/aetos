"""Verify ``real.pkl`` can be turned into DB-compatible JSON (Episode.state / JSONB)."""

from __future__ import annotations

import json

import pytest

@pytest.fixture(scope="module")
def bundle():
    try:
        from tests.real_pkl_loader import load_real_bundle
    except ImportError as e:
        pytest.skip(f"real_pkl_loader import failed: {e}")
    try:
        return load_real_bundle()
    except NotImplementedError as e:
        pytest.skip(f"real.pkl cannot be unpickled on this interpreter: {e}")
    except Exception as e:
        pytest.skip(f"real.pkl load failed: {e}")


def test_bundle_structure(bundle):
    assert isinstance(bundle, dict)
    assert "metadata" in bundle
    assert "timeseries" in bundle
    ts = bundle["timeseries"]
    assert len(ts) > 0
    assert "load_kw" in ts.columns and "price_buy" in ts.columns


def test_slice_maps_to_energy_state_and_json(bundle):
    from tests.real_pkl_loader import (
        energy_state_json_roundtrip,
        timeseries_slice_to_energy_state,
    )

    state = timeseries_slice_to_energy_state(bundle, bus=48, day_offset=0)
    assert len(state.price) == 24
    assert len(state.load) == 24
    assert len(state.generation) == 24
    assert 0.0 <= state.ess_soc <= 1.0
    assert energy_state_json_roundtrip(state)

    raw = json.dumps(state.model_dump())
    assert len(raw) > 100


def test_episode_state_payload_shape(bundle):
    """Same dict shape can be stored in SQLAlchemy JSONB ``Episode.state``."""
    from tests.real_pkl_loader import timeseries_slice_to_energy_state

    state = timeseries_slice_to_energy_state(bundle, bus=48, day_offset=0)
    payload = state.model_dump()
    # JSONB-friendly: lists and floats only
    json.dumps(payload)
    assert isinstance(payload["price"], list)
    assert isinstance(payload["constraints"], dict)
