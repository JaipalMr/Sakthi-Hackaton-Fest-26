import json

import numpy as np
import pandas as pd
import pytest

from backend.app.config import DATA_PATH
from backend.app.errors import ServiceError
from backend.app.schemas import ForecastContext, Scenario
from backend.app import pipeline
from ml.features import FEATURES, TARGET, build_features
from ml.train import chronological_split
from tests.conftest import FEST, ORIGIN


def test_target_not_used_as_feature():
    assert TARGET not in FEATURES
    assert "average_wait_time" not in FEATURES
    assert all("target" not in f for f in FEATURES)


def test_split_is_time_aware_and_leak_free():
    df = pd.read_csv(DATA_PATH); df["timestamp"] = pd.to_datetime(df["timestamp"])
    tr, va, te = chronological_split(df)
    assert (len(tr), len(va), len(te)) == (9000, 3000, 3000)
    assert tr.timestamp.max() < va.timestamp.min() and va.timestamp.max() < te.timestamp.min()


def test_saved_metrics_are_real_and_beat_baseline(svc):
    m = svc.model.metadata
    assert m["data_is_synthetic"] is True
    assert m["test_one_step"]["mae"] < m["baselines"]["baseline_persistence"]["test"]["mae"]
    assert m["test_one_step"]["mae"] < m["baselines"]["baseline_stop_phase_mean"]["test"]["mae"]


def test_predictions_nonnegative_ordered_intervals(svc):
    r = pipeline.predict(svc, ForecastContext(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=8))
    assert len(r.forecasts) == 10 and r.horizon_steps_returned == 8
    for f in r.forecasts:
        assert [s.step for s in f.steps] == list(range(1, 9))
        for s in f.steps:
            assert s.predicted_demand >= 0
            assert 0 <= s.interval_low <= s.predicted_demand + 1e-6 <= s.interval_high + 1e-6
            assert s.actual_demand_synthetic is not None


def test_no_future_target_leakage(svc, monkeypatch):
    """Changing the future TARGET labels must not change predictions."""
    ctx = ForecastContext(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=6)
    a = pipeline.predict(svc, ctx)
    store = svc.store
    original = store.df[TARGET].copy()
    try:
        store.df[TARGET] = (store.df[TARGET] * 7 + 123).astype(int)
        b = pipeline.predict(svc, ctx)
    finally:
        store.df[TARGET] = original
    pa = [s.predicted_demand for f in a.forecasts for s in f.steps]
    pb = [s.predicted_demand for f in b.forecasts for s in f.steps]
    assert pa == pb


def test_horizon_truncated_near_end_of_day(svc):
    r = pipeline.predict(svc, ForecastContext(festival_id=FEST, forecast_origin="2025-11-16T23:45:00", horizon_steps=8))
    assert r.horizon_steps_returned == 3  # 23:45, 00:00, 00:15


def test_unknown_inputs_raise(svc):
    with pytest.raises(ServiceError) as e:
        pipeline.predict(svc, ForecastContext(festival_id="X-1", forecast_origin=ORIGIN))
    assert e.value.status_code == 404
    with pytest.raises(ServiceError) as e:
        pipeline.predict(svc, ForecastContext(festival_id=FEST, forecast_origin="2025-11-16T21:05:00"))
    assert e.value.status_code == 422
    with pytest.raises(ServiceError):
        pipeline.predict(svc, ForecastContext(festival_id=FEST, forecast_origin=ORIGIN, stop_ids=["S99"]))


def test_scenario_changes_predictions_in_sensible_direction(svc):
    ctx = ForecastContext(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=8)
    base = pipeline.predict(svc, ctx)
    later = pipeline.predict(svc, ctx, Scenario(festival_end_shift_min=60))
    assert later.provenance.scenario_applied and base.provenance.scenario_applied is False
    assert all(t.actual_demand_synthetic is None for t in later.totals_by_step)   # no fake "actuals" for what-ifs
    # festival ends later -> dispersal wave starts later -> less demand in the near term (steps 3-4)
    b = {t.step: t.predicted_demand for t in base.totals_by_step}; l = {t.step: t.predicted_demand for t in later.totals_by_step}
    assert l[3] < b[3]
    fewer = pipeline.predict(svc, ctx, Scenario(bus_availability_factor=0.5))
    assert sum(t.available_buses for t in fewer.totals_by_step) < sum(t.available_buses for t in base.totals_by_step)
    closed = pipeline.predict(svc, ctx, Scenario(closed_stop_ids=["S01"]))
    assert all(s.route_closed for s in closed.forecasts[0].steps)
