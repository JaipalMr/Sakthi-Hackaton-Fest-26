"""Read-only access to the synthetic dataset (the 'actual input data' of the dashboard)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backend.app.errors import ServiceError
from ml import network as net
from ml.features import add_derived


class DataStore:
    def __init__(self, path: Path):
        self.path = path
        self.df = pd.read_csv(path)
        self.df["timestamp"] = pd.to_datetime(self.df["timestamp"])
        self.df = self.df.sort_values(["festival_id", "timestamp", "stop_id"]).reset_index(drop=True)
        self.df["service_day"] = (self.df["timestamp"] - pd.Timedelta(hours=12)).dt.normalize()
        self.rain_max = float(self.df["rainfall"].max())

    @property
    def rows(self) -> int:
        return len(self.df)

    def festival_ids(self) -> list[str]:
        return sorted(self.df["festival_id"].unique())

    def festivals(self) -> list[dict]:
        out = []
        for fid, g in self.df.groupby("festival_id"):
            days = []
            for day, gd in g.groupby("service_day"):
                first = gd.iloc[0]
                slots = sorted(gd["timestamp"].unique())
                days.append(dict(
                    date=day.strftime("%Y-%m-%d"), festival_day=int(first["festival_day"]),
                    scheduled_start=first["scheduled_start_time"], scheduled_end=first["scheduled_end_time"],
                    slots=[pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%S") for t in slots]))
            out.append(dict(festival_id=fid, name=net.FESTIVAL_NAMES.get(fid, fid),
                            attendance=int(g["festival_attendance"].iloc[0]), days=days))
        return out

    def stops(self) -> list[dict]:
        return [dict(stop_id=s.stop_id, stop_name=s.stop_name, latitude=s.latitude, longitude=s.longitude,
                     role=s.role, waiting_capacity=s.waiting_capacity, max_buses=s.max_buses,
                     typical_bus_capacity=s.typical_bus_capacity) for s in net.STOPS]

    def window(self, festival_id: str, origin: pd.Timestamp, steps: int) -> tuple[pd.DataFrame, int]:
        """Rows for the first `steps` slots from `origin` (same service day), all stops, with a `step` column."""
        if festival_id not in set(self.df["festival_id"]):
            raise ServiceError(404, f"Unknown festival_id '{festival_id}'. Valid: {self.festival_ids()}", "festival_not_found")
        g = self.df[self.df["festival_id"] == festival_id]
        hit = g[g["timestamp"] == origin]
        if hit.empty:
            lo, hi = g["timestamp"].min(), g["timestamp"].max()
            raise ServiceError(422, f"forecast_origin {origin.isoformat()} is not a 15-minute slot of {festival_id} "
                                    f"(slots run {lo.isoformat()} to {hi.isoformat()}, 12:00-00:15 daily). "
                                    "Use GET /api/festivals for valid slots.", "origin_not_in_dataset")
        day = hit["service_day"].iloc[0]
        gd = g[(g["service_day"] == day) & (g["timestamp"] >= origin)]
        slots = sorted(gd["timestamp"].unique())[:steps]
        gd = gd[gd["timestamp"].isin(slots)].copy()
        step_of = {t: i + 1 for i, t in enumerate(slots)}
        gd["step"] = gd["timestamp"].map(step_of)
        gd = add_derived(gd)
        return gd.sort_values(["stop_id", "step"]).reset_index(drop=True), len(slots)
