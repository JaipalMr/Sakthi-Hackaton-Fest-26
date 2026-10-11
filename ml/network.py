"""Shared network / domain definitions used by the dataset generator, trainer AND the backend.

Everything here is an ILLUSTRATIVE, SYNTHETIC network (fictional stops laid out on a plane and
projected to lat/lon around an arbitrary origin). It does not describe a real transit system.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SLOT_MIN = 15  # one forecast slot = 15 minutes
ORIGIN_LAT, ORIGIN_LON = 12.9716, 77.5946  # arbitrary projection origin (illustrative only)

# ---- documented modelling assumptions shared by generator and what-if simulator -------------
RAIN_TRAVEL_COEF = 0.012      # +1.2% bus travel time per mm/h of rain
CLOSURE_TRAVEL_MULT = 1.6     # detour multiplier on in-service travel time when a stop's route is closed
CLOSURE_BUS_MULT = 0.5        # share of buses still able to operate at a closed stop
CLOSURE_DEMAND_MULT = 0.8     # generator only: demand suppressed at a closed stop (no spill-over modelled)
DWELL_MIN = 8.0               # layover + dwell added to every round trip (minutes)
AVG_SPEED_KMH = 24.0
DETOUR_FACTOR = 1.3
STOP_STOP_OVERHEAD_MIN = 2.0


@dataclass(frozen=True)
class Stop:
    stop_id: str
    stop_name: str
    role: str                 # "venue" (festival-side) or "hub" (origin side)
    x_km: float
    y_km: float
    typical_bus_capacity: int
    waiting_capacity: int     # people the waiting area can hold - an operational ASSUMPTION
    max_buses: int            # bays / kerb space for buses at this stop
    base_buses: int
    arrival_share: float      # share of festival arrivals that board here (hubs)
    dispersal_share: float    # share of festival departures that board here (venue stops)
    background: float         # baseline local riders per slot

    @property
    def latitude(self) -> float:
        return round(ORIGIN_LAT + self.y_km / 111.2, 6)

    @property
    def longitude(self) -> float:
        return round(ORIGIN_LON + self.x_km / (111.2 * math.cos(math.radians(ORIGIN_LAT))), 6)


STOPS: list[Stop] = [
    Stop("S01", "Festival Main Gate",     "venue",  0.0,  0.0, 75, 600, 16, 8, 0.00, 0.45, 3),
    Stop("S02", "North Gate Plaza",       "venue", -0.6,  1.0, 60, 450, 12, 7, 0.00, 0.25, 3),
    Stop("S06", "Stadium Road",           "venue",  0.8, -0.9, 60, 450, 12, 7, 0.00, 0.30, 3),
    Stop("S03", "Riverside Park & Ride",  "hub",    4.8,  3.4, 60, 400, 10, 5, 0.14, 0.00, 10),
    Stop("S04", "Central Railway Station", "hub",  -4.5,  2.5, 75, 600, 12, 6, 0.22, 0.00, 20),
    Stop("S05", "City Bus Terminal",      "hub",   -2.5, -3.8, 60, 500, 12, 6, 0.17, 0.00, 16),
    Stop("S07", "Old Town Market",        "hub",   -1.8,  2.4, 45, 300, 8, 4, 0.10, 0.00, 12),
    Stop("S08", "University Campus",      "hub",   -4.2, -1.2, 60, 350, 10, 5, 0.12, 0.00, 10),
    Stop("S09", "Lakeside Parking",       "hub",    3.8, -4.2, 60, 400, 10, 5, 0.14, 0.00, 6),
    Stop("S10", "Airport Link Road",      "hub",    6.5, -0.8, 45, 250, 8, 4, 0.11, 0.00, 6),
]
STOP_IDS = [s.stop_id for s in STOPS]
_BY_ID = {s.stop_id: s for s in STOPS}

FESTIVALS = [
    dict(festival_id="FEST-2025-01", name="Winter Lights (synthetic)", start_date="2025-01-16",
         attendance=9500, base_temp=22.0, rain_p=0.15),
    dict(festival_id="FEST-2025-02", name="Spring Carnival (synthetic)", start_date="2025-04-10",
         attendance=13500, base_temp=33.0, rain_p=0.10),
    dict(festival_id="FEST-2025-03", name="Monsoon Music Fair (synthetic)", start_date="2025-07-17",
         attendance=11000, base_temp=29.0, rain_p=0.60),
    dict(festival_id="FEST-2025-04", name="Harvest Festival (synthetic)", start_date="2025-09-18",
         attendance=12000, base_temp=28.0, rain_p=0.50),
    dict(festival_id="FEST-2025-05", name="Autumn Lantern Festival (synthetic)", start_date="2025-11-13",
         attendance=12500, base_temp=24.0, rain_p=0.30),
]
FESTIVAL_NAMES = {f["festival_id"]: f["name"] for f in FESTIVALS}


def get_stop(stop_id: str) -> Stop:
    return _BY_ID[stop_id]


def stop_distance_km(a: str, b: str) -> float:
    sa, sb = _BY_ID[a], _BY_ID[b]
    return math.hypot(sa.x_km - sb.x_km, sa.y_km - sb.y_km)


def inter_stop_minutes(a: str, b: str) -> float:
    """Typical (un-congested) bus travel minutes between two stops."""
    if a == b:
        return 0.0
    km = stop_distance_km(a, b) * DETOUR_FACTOR
    return round(km / AVG_SPEED_KMH * 60.0 + STOP_STOP_OVERHEAD_MIN, 1)


def travel_time_matrix(closed: set[str] | None = None) -> dict[tuple[str, str], float | None]:
    """Stop-to-stop minutes; None means infeasible (route closed at either end)."""
    closed = closed or set()
    out: dict[tuple[str, str], float | None] = {}
    for a in STOP_IDS:
        for b in STOP_IDS:
            if a == b:
                continue
            out[(a, b)] = None if (a in closed or b in closed) else inter_stop_minutes(a, b)
    return out


def base_route_minutes(stop_id: str) -> float:
    """In-service route time used for the cycle-time / throughput calculation."""
    s = _BY_ID[stop_id]
    if s.role == "hub":
        return inter_stop_minutes(stop_id, "S01")
    hubs = ["S04", "S05", "S07"]
    return round(float(np.mean([inter_stop_minutes(stop_id, h) for h in hubs])), 1)


def cycle_factor(route_travel_min):
    """Share of a bus's capacity that can be loaded at the stop per 15-minute slot (<=1)."""
    cycle = 2.0 * np.asarray(route_travel_min, dtype=float) + DWELL_MIN
    return np.minimum(1.0, SLOT_MIN / cycle)


def service_capacity(buses, capacity, route_travel_min):
    """Passengers/slot a stop can load = buses x vehicle capacity x cycle factor (never > buses x capacity)."""
    return np.asarray(buses, dtype=float) * np.asarray(capacity, dtype=float) * cycle_factor(route_travel_min)


# ---- time helpers ---------------------------------------------------------------------------
def hhmm_to_minutes(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def minutes_to_hhmm(mins: float) -> str:
    mins = int(round(mins))
    return f"{mins // 60:02d}:{mins % 60:02d}"


def phase_array(minutes_since_start, minutes_to_end) -> np.ndarray:
    ms = np.asarray(minutes_since_start, dtype=float)
    me = np.asarray(minutes_to_end, dtype=float)
    return np.select(
        [ms < -120, ms < 30, me > 30, me > -120],
        ["pre_event", "arrival", "main_event", "dispersal"],
        default="wind_down",
    )


def weather_condition_array(rain, cloud) -> np.ndarray:
    rain = np.asarray(rain, dtype=float)
    cloud = np.asarray(cloud, dtype=float)
    return np.select([rain >= 7.5, rain >= 0.3, cloud > 0.55], ["heavy_rain", "light_rain", "cloudy"], default="clear")
