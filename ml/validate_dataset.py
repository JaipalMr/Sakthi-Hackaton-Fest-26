"""Dataset validation. Exit code 0 = valid, 1 = problems found.

Usage: python -m ml.validate_dataset [path]
NOTE: the dataset is SYNTHETIC; target labels are for demonstration only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from ml import network as net

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "festival_transport_demand.csv"
EXPECTED_ROWS = 15_000
REQUIRED_COLUMNS = [
    "timestamp", "festival_id", "stop_id", "stop_name", "latitude", "longitude", "event_phase",
    "weather_condition", "temperature", "rainfall", "historical_or_observed_passengers",
    "available_buses", "average_bus_capacity", "average_wait_time", "route_travel_time",
    "target_passenger_demand",
]
EXTRA_COLUMNS = ["festival_day", "scheduled_start_time", "scheduled_end_time", "festival_attendance",
                 "stop_capacity", "route_closed", "data_source"]
PHASES = {"pre_event", "arrival", "main_event", "dispersal", "wind_down"}
WEATHER = {"clear", "cloudy", "light_rain", "heavy_rain"}


def validate(df: pd.DataFrame, expected_rows: int = EXPECTED_ROWS) -> list[str]:
    errs: list[str] = []
    if len(df) != expected_rows:
        errs.append(f"row count {len(df)} != expected {expected_rows}")
    missing_cols = [c for c in REQUIRED_COLUMNS + EXTRA_COLUMNS if c not in df.columns]
    if missing_cols:
        errs.append(f"missing columns: {missing_cols}")
        return errs
    na = df[REQUIRED_COLUMNS + EXTRA_COLUMNS].isna().sum()
    if na.sum():
        errs.append(f"missing values: {na[na > 0].to_dict()}")
    ts = pd.to_datetime(df["timestamp"], errors="coerce", format="%Y-%m-%dT%H:%M:%S")
    if ts.isna().any():
        errs.append(f"{int(ts.isna().sum())} invalid timestamps")
    dups = df.duplicated(["timestamp", "festival_id", "stop_id"]).sum()
    if dups:
        errs.append(f"{int(dups)} duplicate (timestamp, festival_id, stop_id) keys")
    # identifier consistency
    ref = {s.stop_id: (s.stop_name, s.latitude, s.longitude) for s in net.STOPS}
    unknown = set(df["stop_id"]) - set(ref)
    if unknown:
        errs.append(f"unknown stop ids: {sorted(unknown)}")
    else:
        for sid, grp in df.groupby("stop_id"):
            if grp[["stop_name", "latitude", "longitude"]].drop_duplicates().shape[0] != 1:
                errs.append(f"{sid}: inconsistent name/lat/lon")
            elif tuple(grp[["stop_name", "latitude", "longitude"]].iloc[0]) != ref[sid]:
                errs.append(f"{sid}: attributes differ from network definition")
    # categorical domains
    if not set(df["event_phase"]) <= PHASES:
        errs.append(f"bad event_phase values {set(df['event_phase']) - PHASES}")
    if not set(df["weather_condition"]) <= WEATHER:
        errs.append(f"bad weather_condition values {set(df['weather_condition']) - WEATHER}")
    if not (df["data_source"] == "synthetic").all():
        errs.append("data_source must be 'synthetic' for every row")
    # ranges
    def rng(col, lo, hi):
        bad = ((df[col] < lo) | (df[col] > hi)).sum()
        if bad:
            errs.append(f"{col}: {int(bad)} values outside [{lo}, {hi}]")
    rng("target_passenger_demand", 0, 5000)
    rng("historical_or_observed_passengers", 0, 5000)
    rng("available_buses", 0, 20)
    rng("average_bus_capacity", 40, 90)
    rng("average_wait_time", 0.5, 75)
    rng("route_travel_time", 3, 120)
    rng("rainfall", 0, 40)
    rng("temperature", 5, 45)
    rng("latitude", -90, 90)
    rng("longitude", -180, 180)
    rng("route_closed", 0, 1)
    for col in ["target_passenger_demand", "historical_or_observed_passengers", "available_buses", "average_bus_capacity"]:
        if not (df[col] == df[col].round()).all():
            errs.append(f"{col} must be integer-valued")
    # coherence
    cap = df.groupby("stop_id")["average_bus_capacity"].agg(["min", "max"])
    for sid, r in cap.iterrows():
        typical = net.get_stop(sid).typical_bus_capacity
        if r["min"] < typical - 5 or r["max"] > typical + 5:
            errs.append(f"{sid}: bus capacity outside typical +-5")
    over = (df["available_buses"] > df["stop_id"].map({s.stop_id: s.max_buses for s in net.STOPS})).sum()
    if over:
        errs.append(f"{int(over)} rows exceed stop bay capacity")
    wet = df[(df["weather_condition"].isin(["light_rain", "heavy_rain"])) & (df["rainfall"] < 0.3)]
    dry = df[(df["weather_condition"].isin(["clear", "cloudy"])) & (df["rainfall"] >= 0.3)]
    if len(wet) or len(dry):
        errs.append("weather_condition inconsistent with rainfall")
    per_series = df.groupby(["festival_id", "festival_day", "stop_id"]).size()
    if per_series.nunique() != 1:
        errs.append("series have unequal slot counts")
    return errs


def main(path: str | None = None) -> int:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        print(f"FAIL: {p} not found. Run: python -m ml.generate_dataset")
        return 1
    df = pd.read_csv(p)
    errs = validate(df)
    print(f"Rows (excluding header): {len(df):,}")
    print(f"Columns: {len(df.columns)}  Festivals: {df['festival_id'].nunique()}  Stops: {df['stop_id'].nunique()}")
    print("NOTE: dataset is SYNTHETIC; target labels are for demonstration only.")
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
