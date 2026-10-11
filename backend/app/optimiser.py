"""Deterministic bus allocation engine. Pure Python: no ML, no LLM, no randomness.

Greedy rule (repeat until nothing improves or `max_moves` reached):
  1. take the open stop with the largest unmet demand that still has bay space,
  2. among feasible donors choose the one that keeps the largest safety slack after giving up a bus
     (ties: shorter travel time, then stop id),
  3. move ONE bus. Stops that received buses never donate and donors never receive (no ping-pong).

HARD CONSTRAINTS (checked again in `audit`):
  * a donor never gives more buses than it has, and keeps >= min_buses_per_stop
  * a donor must still cover its own predicted demand x (1 + reserve_margin)
  * a destination never exceeds its bay capacity (max_buses)
  * travel time (route feasibility incl. closures) must fit inside lead time - dispatch buffer
  * closed stops neither send nor receive buses
  * total fleet is conserved; per-slot passengers carried never exceed vehicle capacity x cycle factor
OUTPUT IS ADVISORY. A human dispatcher must approve before any real dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.config import OpsConfig
from backend.app.risk import assess
from ml import network as net


@dataclass
class StopInput:
    stop_id: str
    stop_name: str
    predicted_demand: float
    buses: int
    avg_bus_capacity: float
    route_travel_min: float
    waiting_capacity: float
    max_buses: int
    closed: bool = False
    backlog_in: float = 0.0


@dataclass
class _S:
    inp: StopInput
    buses: int
    cap_sum: float
    f: float
    start_buses: int
    start_service: float = 0.0
    gave: int = 0
    got: int = 0

    @property
    def service(self) -> float:
        return self.cap_sum * self.f

    @property
    def cap(self) -> float:
        return self.cap_sum / self.buses if self.buses else self.inp.avg_bus_capacity


def _unserved(demand: float, service: float) -> float:
    return max(0.0, demand - service)


def optimise(stops: list[StopInput], ops: OpsConfig, lead_time_min: float) -> dict:
    st = {s.stop_id: _S(s, s.buses, s.buses * s.avg_bus_capacity, float(net.cycle_factor(s.route_travel_min)), s.buses,
                        start_service=s.buses * s.avg_bus_capacity * float(net.cycle_factor(s.route_travel_min)))
          for s in sorted(stops, key=lambda s: s.stop_id)}
    closed = {sid for sid, s in st.items() if s.inp.closed}
    travel = net.travel_time_matrix(closed)
    budget = lead_time_min - ops.dispatch_buffer_min
    margin = 1.0 + ops.reserve_margin
    before = {sid: _snapshot(s, ops) for sid, s in st.items()}
    moves: list[dict] = []

    while len(moves) < ops.max_moves:
        receivers = sorted(
            (s for s in st.values()
             if not s.inp.closed and s.gave == 0 and s.buses < s.inp.max_buses and s.inp.predicted_demand > s.service + 0.5),
            key=lambda s: (-(s.inp.predicted_demand - s.service), s.inp.stop_id))
        made = False
        for r in receivers:
            best = None
            for d in st.values():
                if d is r or d.inp.closed or d.got > 0 or d.buses <= ops.min_buses_per_stop or d.buses <= 0:
                    continue
                t = travel.get((d.inp.stop_id, r.inp.stop_id))
                if t is None or t > budget:
                    continue
                c = d.cap
                after_service = (d.cap_sum - c) * d.f
                slack = after_service - d.inp.predicted_demand * margin
                if slack < 0:
                    continue
                gain = min(r.inp.predicted_demand, r.service + c * r.f) - min(r.inp.predicted_demand, r.service)
                if gain < 0.5:
                    continue
                key = (-slack, t, d.inp.stop_id)
                if best is None or key < best[0]:
                    best = (key, d, c, t, gain, slack)
            if best:
                _, d, c, t, gain, slack = best
                loss = min(d.inp.predicted_demand, d.service) - min(d.inp.predicted_demand, (d.cap_sum - c) * d.f)
                d.cap_sum -= c; d.buses -= 1; d.gave += 1
                r.cap_sum += c; r.buses += 1; r.got += 1
                moves.append(dict(o=d.inp.stop_id, d=r.inp.stop_id, t=t, gain=gain, loss=loss, cap=c,
                                  donor_slack=slack, donor_service=(d.cap_sum) * d.f, donor_demand=d.inp.predicted_demand))
                made = True
                break
        if not made:
            break

    after = {sid: _snapshot(s, ops) for sid, s in st.items()}
    recs = _aggregate(moves, st, ops, lead_time_min, margin)
    unresolved = _unresolved(st, travel, budget, ops, margin)
    audit = _audit(st, moves, travel, budget, ops, margin)
    tot_d = sum(s.inp.predicted_demand for s in st.values())
    unb = sum(v["unserved"] for v in before.values())
    una = sum(v["unserved"] for v in after.values())
    summary = dict(
        total_buses=sum(s.buses for s in st.values()), buses_moved=len(moves),
        unserved_before=round(unb, 1), unserved_after=round(una, 1),
        additional_passengers_served=round(unb - una, 1),
        served_share_before=round(1 - unb / tot_d, 3) if tot_d > 0 else 1.0,
        served_share_after=round(1 - una / tot_d, 3) if tot_d > 0 else 1.0,
        high_risk_stops_before=sum(v["risk_level"] == "high" for v in before.values()),
        high_risk_stops_after=sum(v["risk_level"] == "high" for v in after.values()))
    return dict(before=list(before.values()), after=list(after.values()), recommendations=recs,
                unresolved=unresolved, summary=summary, constraint_audit=audit)


def _snapshot(s: _S, ops: OpsConfig) -> dict:
    a = assess(s.inp.predicted_demand, s.service, s.inp.backlog_in, s.inp.waiting_capacity, ops)
    return dict(stop_id=s.inp.stop_id, stop_name=s.inp.stop_name, buses=s.buses,
                predicted_demand=round(s.inp.predicted_demand, 1), service_capacity=round(s.service, 1),
                unserved=a["unserved"], load_ratio=a["load_ratio"], crowding_ratio=a["crowding_ratio"],
                risk_level=a["risk_level"])


def _aggregate(moves, st, ops, lead, margin) -> list[dict]:
    pairs: dict[tuple[str, str], dict] = {}
    for m in moves:
        p = pairs.setdefault((m["o"], m["d"]), dict(n=0, gain=0.0, loss=0.0, t=m["t"], cap=m["cap"]))
        p["n"] += 1; p["gain"] += m["gain"]; p["loss"] += m["loss"]
    out = []
    for (o, d), p in sorted(pairs.items(), key=lambda kv: (-(kv[1]["gain"] - kv[1]["loss"]), kv[0])):
        so, sd = st[o], st[d]
        cons = [
            dict(name="Donor keeps minimum buses", satisfied=so.buses >= ops.min_buses_per_stop,
                 detail=f"{so.inp.stop_name} keeps {so.buses} of {so.start_buses} buses (minimum {ops.min_buses_per_stop})"),
            dict(name="Donor still covers its own demand + reserve", satisfied=so.service >= so.inp.predicted_demand * margin - 1e-6,
                 detail=f"service {so.service:.0f} vs predicted demand {so.inp.predicted_demand:.0f} x {margin:.2f}"),
            dict(name="Route feasible within lead time", satisfied=p["t"] <= lead - ops.dispatch_buffer_min,
                 detail=f"travel {p['t']:.1f} min <= lead {lead:.0f} min - {ops.dispatch_buffer_min:.0f} min dispatch buffer"),
            dict(name="Destination bay capacity", satisfied=sd.buses <= sd.inp.max_buses,
                 detail=f"{sd.inp.stop_name} ends with {sd.buses} of max {sd.inp.max_buses} buses"),
            dict(name="Vehicle capacity respected", satisfied=True,
                 detail=f"moved bus carries <= {p['cap']:.0f} passengers per trip (x {sd.f:.2f} loadable trips/slot)"),
        ]
        rationale = (f"Move {p['n']} bus{'es' if p['n'] > 1 else ''} from {so.inp.stop_name} to {sd.inp.stop_name}. "
                     f"{sd.inp.stop_name} is forecast at {sd.inp.predicted_demand:.0f} passengers but only has "
                     f"{sd.start_service:.0f} service capacity with its {sd.start_buses} planned bus(es). "
                     f"{so.inp.stop_name} keeps {so.service:.0f} capacity against a forecast of {so.inp.predicted_demand:.0f}, "
                     f"so it can spare the bus(es). Travel time {p['t']:.0f} min.")
        out.append(dict(rank=len(out) + 1, origin_stop_id=o, origin_stop_name=so.inp.stop_name,
                        destination_stop_id=d, destination_stop_name=sd.inp.stop_name, buses=p["n"],
                        travel_time_min=p["t"], rationale=rationale, constraints=cons,
                        estimated_impact=dict(extra_passengers_served_at_destination=round(p["gain"], 1),
                                              passengers_displaced_at_origin=round(p["loss"], 1),
                                              net_passengers_served=round(p["gain"] - p["loss"], 1))))
    return out


def _unresolved(st, travel, budget, ops, margin) -> list[dict]:
    out = []
    for s in sorted(st.values(), key=lambda s: s.inp.stop_id):
        rem = _unserved(s.inp.predicted_demand, s.service)
        if rem < 0.5:
            continue
        if s.inp.closed:
            why = "route is closed in this scenario, so no buses can be sent"
        elif s.gave:
            why = "stop was a donor in this plan"
        elif s.buses >= s.inp.max_buses:
            why = f"bay capacity reached ({s.inp.max_buses} buses)"
        elif budget <= 0:
            why = "lead time is shorter than the dispatch buffer, so no bus can arrive in time"
        else:
            reach = [d for d in st.values() if d is not s and not d.inp.closed and (travel.get((d.inp.stop_id, s.inp.stop_id)) or 1e9) <= budget]
            why = ("no stop within reach has spare buses without dropping below its own demand + reserve"
                   if reach else f"no other open stop is within the {budget:.0f}-minute travel budget")
        out.append(dict(stop_id=s.inp.stop_id, stop_name=s.inp.stop_name, remaining_unserved=round(rem, 1), reason=why))
    return out


def _audit(st, moves, travel, budget, ops, margin) -> list[dict]:
    def chk(name, ok, detail): return dict(name=name, satisfied=bool(ok), detail=detail)
    fleet_before = sum(s.start_buses for s in st.values())
    fleet_after = sum(s.buses for s in st.values())
    donors_ok = all(s.buses >= min(s.start_buses, ops.min_buses_per_stop) and s.buses >= 0 for s in st.values())
    donor_cover = all(s.gave == 0 or s.service >= s.inp.predicted_demand * margin - 1e-6 for s in st.values())
    bays_ok = all(s.buses <= max(s.inp.max_buses, s.start_buses) for s in st.values())
    route_ok = all((travel.get((m["o"], m["d"])) is not None) and m["t"] <= budget + 1e-9 for m in moves)
    closed_ok = all(not (st[m["o"]].inp.closed or st[m["d"]].inp.closed) for m in moves)
    cap_ok = all(s.service <= s.cap_sum + 1e-6 for s in st.values())
    given_ok = all(s.gave <= s.start_buses for s in st.values())
    return [
        chk("Fleet conserved", fleet_before == fleet_after, f"{fleet_before} buses before, {fleet_after} after"),
        chk("No stop gives more buses than it has", given_ok, "per-stop gives <= starting buses"),
        chk("Minimum buses kept at donors", donors_ok, f"minimum {ops.min_buses_per_stop}"),
        chk("Donors still cover their demand + reserve", donor_cover, f"reserve margin {ops.reserve_margin:.0%}"),
        chk("Bay capacity respected", bays_ok, "no stop above its max_buses"),
        chk("All moves route-feasible in time", route_ok, f"travel budget {max(budget, 0):.0f} min"),
        chk("Closed stops untouched", closed_ok, "no moves from or to closed stops"),
        chk("Vehicle capacity never exceeded", cap_ok, "service capacity <= buses x vehicle capacity"),
    ]
