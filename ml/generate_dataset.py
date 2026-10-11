"""Reproducible SYNTHETIC dataset generator -> data/festival_transport_demand.csv

5 festivals x 6 days x 50 fifteen-minute slots (12:00 -> 00:15) x 10 stops = 15,000 rows.

THIS DATA IS SYNTHETIC. It is produced by a documented simulation (see data/README.md) and does NOT
represent real observations. Target labels are for demonstration of the pipeline only.

Usage:  python -m ml.generate_dataset
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from ml import network as net

SEED = 20250615
N_DAYS = 6
N_SLOTS = 50                     # 12:00 .. 00:15 inclusive, 15-min slots
DAY_START_MIN = 12 * 60          # first slot starts 12:00
MODE_SHARE = 0.44                # share of attendees using festival bus service (assumption)
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "festival_transport_demand.csv"

START_CHOICES = [15 * 60, 15 * 60 + 30, 16 * 60, 16 * 60 + 30]
END_CHOICES = [21 * 60 + 30, 22 * 60, 22 * 60 + 30, 23 * 60]


# ---- demand profile building blocks (per 15-min slot, each integrates to ~1) -----------------
def _normal_mass(m, mu, sd):
    return np.exp(-0.5 * ((m - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi)) * net.SLOT_MIN


def _gamma_mass(x, k, theta):
    x = np.asarray(x, dtype=float)
    out = np.zeros_like(x)
    pos = x > 0
    out[pos] = np.exp((k - 1) * np.log(x[pos]) - x[pos] / theta - math.lgamma(k) - k * math.log(theta)) * net.SLOT_MIN
    return out


def arrival_profile(m, start):
    return _normal_mass(m, start - 45, 55)


def dispersal_profile(m, start, end):
    """85% leave in a gamma-shaped wave after the end; 15% leave steadily during the event."""
    gamma = _gamma_mass(m - (end - 25), 2.2, 32.0)
    lo = start + 60
    early = np.where((m >= lo) & (m <= end - 30), net.SLOT_MIN / max(end - 30 - lo, 1), 0.0)
    return 0.85 * gamma + 0.15 * early


def diurnal(m):
    hours = m / 60.0
    return np.interp(hours, [12, 16, 19, 22, 24.5], [0.6, 0.8, 1.0, 0.9, 0.4])


def stop_flow(m, start, end, riders):
    """Mean demand matrix [stops, slots] from flows only (no background, noise or weather)."""
    out = np.zeros((len(net.STOPS), len(m)))
    a, d = arrival_profile(m, start), dispersal_profile(m, start, end)
    for i, s in enumerate(net.STOPS):
        out[i] = riders * (s.arrival_share * a + s.dispersal_share * d)
    return out


def generate(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    K = N_SLOTS + 1  # index 0 is the pre-service lag slot (11:45) used only to build lag features
    for fest in net.FESTIVALS:
        base_date = pd.Timestamp(fest["start_date"])
        for day in range(N_DAYS):
            date = base_date + pd.Timedelta(days=day)
            minutes = DAY_START_MIN + (np.arange(K) - 1) * net.SLOT_MIN
            ts = date + pd.to_timedelta(minutes, unit="m")
            start = int(rng.choice(START_CHOICES))
            end = int(rng.choice(END_CHOICES, p=[0.2, 0.3, 0.3, 0.2]))

            # --- weather ---------------------------------------------------------------------
            cloud = np.zeros(K)
            base_cloud = rng.uniform(0.2, 0.7)
            cloud[0] = base_cloud
            for k in range(1, K):
                cloud[k] = np.clip(0.9 * cloud[k - 1] + 0.1 * base_cloud + rng.normal(0, 0.07), 0, 1)
            rain = np.zeros(K)
            if rng.random() < fest["rain_p"]:
                r0, dur = int(rng.integers(0, K - 6)), int(rng.integers(4, 17))
                peak = float(np.exp(rng.normal(np.log(5.5), 0.7)))
                for k in range(r0, min(K, r0 + dur)):
                    rain[k] = peak * math.sin(math.pi * (k - r0 + 0.5) / dur) * (1 + rng.normal(0, 0.15))
            elif rng.random() < 0.1:
                r0 = int(rng.integers(0, K - 4))
                rain[r0:r0 + 3] = rng.uniform(0.3, 1.0, size=min(3, K - r0))
            rain = np.round(np.clip(rain, 0, 25), 1)
            cloud = np.where(rain > 0.3, np.maximum(cloud, 0.7), cloud)
            day_temp = fest["base_temp"] + rng.normal(0, 2.0)
            temp = day_temp + 4.0 * np.cos(2 * math.pi * (minutes / 60.0 - 15) / 24.0) \
                - 3.0 * np.minimum(rain / 5.0, 1.0) + rng.normal(0, 0.4, K)
            temp = np.round(temp, 1)
            cond = net.weather_condition_array(rain, cloud)

            # --- closures --------------------------------------------------------------------
            closed = np.zeros((len(net.STOPS), K), dtype=bool)
            if rng.random() < 0.5:
                i = int(rng.integers(0, len(net.STOPS)))
                c0, clen = int(rng.integers(8, 35)), int(rng.integers(8, 17))
                closed[i, c0:c0 + clen] = True

            # --- demand ----------------------------------------------------------------------
            dow = date.dayofweek
            dow_factor = {0: 0.85, 1: 0.85, 2: 0.85, 3: 0.9, 4: 1.0, 5: 1.2, 6: 1.15}[dow]
            ramp = 0.9 + 0.04 * day
            riders = fest["attendance"] * MODE_SHARE * dow_factor * ramp * float(np.exp(rng.normal(0, 0.05)))
            weather_mult = (1 + 0.035 * np.minimum(rain, 12)) * (1 + 0.01 * np.maximum(0, temp - 33))
            flow = stop_flow(minutes.astype(float), start, end, riders) * weather_mult
            demand = np.zeros_like(flow)
            for i, s in enumerate(net.STOPS):
                mean = flow[i] + s.background * diurnal(minutes.astype(float))
                mean = np.where(closed[i], mean * net.CLOSURE_DEMAND_MULT, mean)
                e = float(np.exp(rng.normal(0, 0.10)))
                u = np.zeros(K)
                for k in range(1, K):
                    u[k] = 0.6 * u[k - 1] + rng.normal(0, 0.07)
                demand[i] = rng.poisson(np.maximum(mean * e * np.exp(u), 0))

            # --- fleet plan (imperfect: planners use shifted timing and a mis-estimated crowd) -----
            shift = int(rng.choice([-30, -15, 0, 15, 30]))
            plan_riders = fest["attendance"] * MODE_SHARE * float(rng.uniform(0.8, 1.2))
            plan = stop_flow(minutes.astype(float), start + shift, end + shift, plan_riders)

            buses = np.zeros((len(net.STOPS), K), dtype=int)
            cap = np.zeros(len(net.STOPS), dtype=int)
            rt = np.zeros((len(net.STOPS), K))
            congestion = np.clip(arrival_profile(minutes.astype(float), start) / 0.11
                                 + dispersal_profile(minutes.astype(float), start, end) / 0.17, 0, 1)
            for i, s in enumerate(net.STOPS):
                load = plan[i] / max(plan[i].max(), 1e-9) if plan[i].max() > 0 else np.zeros(K)
                b = s.base_buses * (0.55 + 0.85 * load ** 0.7) + rng.normal(0, 0.35, K)
                b = np.round(b)
                if rng.random() < 0.15:  # breakdown / driver shortage window
                    d0, dlen = int(rng.integers(0, K - 8)), int(rng.integers(8, 21))
                    b[d0:d0 + dlen] -= int(rng.integers(1, 3))
                b = np.where(closed[i], np.round(b * net.CLOSURE_BUS_MULT), b)
                buses[i] = np.clip(b, 0, s.max_buses).astype(int)
                cap[i] = s.typical_bus_capacity + int(rng.choice([-5, 0, 0, 5]))
                base_rt = net.base_route_minutes(s.stop_id)
                mult = (1 + 0.25 * congestion) * (1 + net.RAIN_TRAVEL_COEF * rain) \
                    * np.where(closed[i], net.CLOSURE_TRAVEL_MULT, 1.0) * np.exp(rng.normal(0, 0.03, K))
                rt[i] = np.round(base_rt * mult, 1)
            buses[:, 0] = buses[:, 1]
            rt[:, 0] = rt[:, 1]

            # --- queue + wait (wait is measured over the PREVIOUS slot -> no target leakage) ------
            service = net.service_capacity(buses, cap[:, None], rt)
            queue_end = np.zeros_like(service)
            for i in range(len(net.STOPS)):
                q = 0.0
                for k in range(K):
                    q += demand[i, k]
                    served = min(q, service[i, k])
                    q -= served
                    queue_end[i, k] = q

            for i, s in enumerate(net.STOPS):
                for k in range(1, K):
                    cycle_prev = 2 * rt[i, k - 1] + net.DWELL_MIN
                    headway = cycle_prev / max(buses[i, k - 1], 0.5)
                    wait = 0.5 * headway + 15.0 * queue_end[i, k - 1] / max(service[i, k - 1], 1.0) + rng.normal(0, 0.5)
                    hist = int(round(demand[i, k - 1] * math.exp(rng.normal(0, 0.05))))
                    m = float(minutes[k])
                    ms, me = m - start, end - m
                    rows.append(dict(
                        timestamp=ts[k].strftime("%Y-%m-%dT%H:%M:%S"),
                        festival_id=fest["festival_id"],
                        festival_day=day + 1,
                        scheduled_start_time=net.minutes_to_hhmm(start),
                        scheduled_end_time=net.minutes_to_hhmm(end),
                        festival_attendance=fest["attendance"],
                        stop_id=s.stop_id,
                        stop_name=s.stop_name,
                        latitude=s.latitude,
                        longitude=s.longitude,
                        stop_capacity=s.waiting_capacity,
                        event_phase=str(net.phase_array(ms, me)),
                        weather_condition=str(cond[k]),
                        temperature=float(temp[k]),
                        rainfall=float(rain[k]),
                        route_closed=int(closed[i, k]),
                        historical_or_observed_passengers=max(hist, 0),
                        available_buses=int(buses[i, k]),
                        average_bus_capacity=int(cap[i]),
                        average_wait_time=round(float(np.clip(wait, 1.0, 75.0)), 1),
                        route_travel_time=float(rt[i, k]),
                        target_passenger_demand=int(demand[i, k]),
                        data_source="synthetic",
                    ))
    df = pd.DataFrame(rows).sort_values(["timestamp", "festival_id", "stop_id"]).reset_index(drop=True)
    return df


def main() -> None:
    df = generate()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(df):,} synthetic rows (excluding header) -> {OUT_PATH}")


if __name__ == "__main__":
    main()
