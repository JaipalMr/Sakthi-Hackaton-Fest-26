"""Applies what-if assumptions to FORECAST-INPUT rows (never to observed history).

All scenario effects reuse the generator's documented relationships (ml/network.py):
  * rainfall:  route_travel_time scales by (1 + 0.012 * rain); weather_condition re-derived from rainfall
  * closure:   buses x 0.5, route_travel_time x 1.6, route_closed = 1 (the model learned the demand effect)
  * end shift: scheduled end moves; minutes_to_end and event_phase are recomputed
  * bus factor: buses x factor, rounded and clipped to bay capacity
These are SIMULATED ASSUMPTIONS, not verified real-world outcomes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.schemas import Scenario
from ml import network as net
from ml.features import add_derived

TRAIN_END_RANGE = (net.hhmm_to_minutes("21:30"), net.hhmm_to_minutes("23:00"))


def apply_scenario(window: pd.DataFrame, sc: Scenario, rain_max_seen: float) -> tuple[pd.DataFrame, list[str]]:
    d = window.copy()
    warnings: list[str] = []
    max_buses = d["stop_id"].map({s.stop_id: s.max_buses for s in net.STOPS})

    if sc.festival_end_shift_min:
        d["end_min"] = d["end_min"] + sc.festival_end_shift_min
        new_end = int(d["end_min"].iloc[0])
        if not (TRAIN_END_RANGE[0] <= new_end <= TRAIN_END_RANGE[1]):
            warnings.append(f"Scenario end time {net.minutes_to_hhmm(new_end)} lies outside the 21:30-23:00 range seen in "
                            "training data; the model is extrapolating.")
    if sc.rainfall_mm_per_hr is not None:
        old, new = d["rainfall"], sc.rainfall_mm_per_hr
        d["route_travel_time"] = np.round(d["route_travel_time"] / (1 + net.RAIN_TRAVEL_COEF * old)
                                          * (1 + net.RAIN_TRAVEL_COEF * new), 1)
        d["rainfall"] = float(new)
        keep = np.where(d["weather_condition"].isin(["clear", "cloudy"]), d["weather_condition"], "cloudy")
        d["weather_condition"] = np.where(new >= 7.5, "heavy_rain", np.where(new >= 0.3, "light_rain", keep))
        if new > rain_max_seen:
            warnings.append(f"Scenario rainfall {new:g} mm/h exceeds the maximum in training data ({rain_max_seen:.1f}); extrapolation.")
    if sc.bus_availability_factor != 1.0:
        d["available_buses"] = np.clip(np.floor(d["available_buses"] * sc.bus_availability_factor + 0.5), 0, max_buses).astype(int)
        if sc.bus_availability_factor < 0.5:
            warnings.append("Bus availability below 50% of plan is far outside historical fleet levels.")
    if sc.closed_stop_ids:
        mask = d["stop_id"].isin(sc.closed_stop_ids) & (d["route_closed"] == 0)
        d.loc[mask, "available_buses"] = np.floor(d.loc[mask, "available_buses"] * net.CLOSURE_BUS_MULT + 0.5).astype(int)
        d.loc[mask, "route_travel_time"] = np.round(d.loc[mask, "route_travel_time"] * net.CLOSURE_TRAVEL_MULT, 1)
        d.loc[d["stop_id"].isin(sc.closed_stop_ids), "route_closed"] = 1
        warnings.append("Closure model: no passenger spill-over to neighbouring stops is simulated.")
    d = add_derived(d)
    d["event_phase"] = net.phase_array(d["minutes_since_start"], d["minutes_to_end"])
    return d, warnings
