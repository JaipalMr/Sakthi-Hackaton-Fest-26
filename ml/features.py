"""Feature engineering shared by training and backend inference (single source of truth).

LEAKAGE POLICY
  * `target_passenger_demand` is NEVER an input. The only demand-derived input is
    `historical_or_observed_passengers`, defined as the passenger count of the PREVIOUS 15-minute slot.
  * `average_wait_time` is measured over the previous slot and is not available for future horizons,
    so it is deliberately excluded from model features.
  * Weather, scheduled event times, fleet plan and route travel time of the forecast slots are treated as
    planning/forecast inputs (the dataset's realised values stand in for perfect forecasts).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml import network as net

CATEGORICAL = ["stop_id", "event_phase", "weather_condition"]
NUMERIC = [
    "clock_minutes", "day_of_week", "festival_day", "minutes_since_start", "minutes_to_end",
    "temperature", "rainfall", "route_closed", "lag_passengers", "available_buses",
    "average_bus_capacity", "route_travel_time", "festival_attendance", "stop_capacity",
    "service_capacity_est",
]
FEATURES = CATEGORICAL + NUMERIC
TARGET = "target_passenger_demand"


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Add time-derived columns. Uses start_min/end_min when present (what-if overrides), else parses HH:MM."""
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"])
    service_date = (d["timestamp"] - pd.Timedelta(hours=12)).dt.normalize()
    d["clock_minutes"] = (d["timestamp"] - service_date).dt.total_seconds() / 60.0
    d["day_of_week"] = service_date.dt.dayofweek
    if "start_min" not in d:
        d["start_min"] = d["scheduled_start_time"].map(net.hhmm_to_minutes)
    if "end_min" not in d:
        d["end_min"] = d["scheduled_end_time"].map(net.hhmm_to_minutes)
    d["minutes_since_start"] = d["clock_minutes"] - d["start_min"]
    d["minutes_to_end"] = d["end_min"] - d["clock_minutes"]
    d["service_capacity_est"] = net.service_capacity(
        d["available_buses"], d["average_bus_capacity"], d["route_travel_time"])
    d["lag_passengers"] = d["historical_or_observed_passengers"].astype(float)
    return d


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    d = add_derived(df)
    return d[FEATURES].copy()


def series_key(df: pd.DataFrame) -> pd.Series:
    d = df
    day = (pd.to_datetime(d["timestamp"]) - pd.Timedelta(hours=12)).dt.normalize().astype(str)
    return d["festival_id"] + "|" + day + "|" + d["stop_id"]
