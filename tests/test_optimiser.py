import random

from backend.app.config import OpsConfig
from backend.app.optimiser import StopInput, optimise
from backend.app.schemas import OptimiseRequest
from backend.app import pipeline
from ml import network as net
from tests.conftest import FEST, ORIGIN


def mk(sid, demand, buses, cap=60, rt=18.0, max_buses=12, closed=False):
    s = net.get_stop(sid)
    return StopInput(sid, s.stop_name, demand, buses, cap, rt, s.waiting_capacity, max_buses, closed)


def _check_invariants(inputs, res, ops, lead):
    moves = res["recommendations"]
    start = {s.stop_id: s.buses for s in inputs}
    after = {a["stop_id"]: a["buses"] for a in res["after"]}
    assert sum(start.values()) == sum(after.values())                          # fleet conserved
    gave, got = {}, {}
    for r in moves:
        assert r["buses"] >= 1 and r["origin_stop_id"] != r["destination_stop_id"]
        gave[r["origin_stop_id"]] = gave.get(r["origin_stop_id"], 0) + r["buses"]
        got[r["destination_stop_id"]] = got.get(r["destination_stop_id"], 0) + r["buses"]
        assert r["travel_time_min"] <= lead - ops.dispatch_buffer_min + 1e-9    # feasible in time
    for s in inputs:
        assert gave.get(s.stop_id, 0) <= s.buses                                # never gives more than it has
        if gave.get(s.stop_id):
            assert after[s.stop_id] >= ops.min_buses_per_stop
        assert after[s.stop_id] <= max(s.max_buses, s.buses)                    # bay capacity
        assert not (s.closed and (gave.get(s.stop_id) or got.get(s.stop_id)))   # closed stops untouched
    for a, i in zip(res["after"], inputs):
        assert a["service_capacity"] <= a["buses"] * 90 + 1e-6                  # <= vehicle capacity (max 90 in data)
    assert all(c["satisfied"] for c in res["constraint_audit"])
    assert res["summary"]["unserved_after"] <= res["summary"]["unserved_before"] + 1e-6


def test_simple_move_from_surplus_to_deficit():
    inputs = [mk("S01", 300, 4), mk("S04", 10, 8), mk("S05", 10, 6)]
    ops = OpsConfig()
    res = optimise(inputs, ops, lead_time_min=30)
    assert res["recommendations"] and res["summary"]["unserved_after"] < res["summary"]["unserved_before"]
    assert all(r["destination_stop_id"] == "S01" for r in res["recommendations"])
    _check_invariants(inputs, res, ops, 30)


def test_no_moves_when_lead_time_too_short():
    inputs = [mk("S01", 300, 4), mk("S04", 10, 8)]
    res = optimise(inputs, OpsConfig(), lead_time_min=5)  # <= dispatch buffer
    assert res["recommendations"] == []
    assert res["unresolved"] and "lead time" in res["unresolved"][0]["reason"]


def test_closed_stop_never_used_and_deterministic():
    inputs = [mk("S01", 300, 4), mk("S04", 10, 8, closed=True), mk("S05", 10, 6)]
    r1, r2 = optimise(inputs, OpsConfig(), 45), optimise(inputs, OpsConfig(), 45)
    assert r1 == r2
    assert all(r["origin_stop_id"] != "S04" for r in r1["recommendations"])
    _check_invariants(inputs, r1, OpsConfig(), 45)


def test_bay_capacity_limits_destination():
    inputs = [mk("S01", 900, 5, max_buses=6), mk("S04", 5, 8), mk("S05", 5, 8)]
    res = optimise(inputs, OpsConfig(), 45)
    after = {a["stop_id"]: a["buses"] for a in res["after"]}
    assert after["S01"] <= 6
    assert any(u["stop_id"] == "S01" and "bay capacity" in u["reason"] for u in res["unresolved"])


def test_donor_keeps_enough_capacity():
    # S04 demand needs all its buses -> must not donate
    inputs = [mk("S01", 300, 3), mk("S04", 100, 4)]
    res = optimise(inputs, OpsConfig(), 45)
    for a in res["after"]:
        if a["stop_id"] == "S04":
            assert a["service_capacity"] >= a["predicted_demand"] * 1.1 - 1e-6 or a["buses"] == 4


def test_randomised_invariants():
    rng, ids = random.Random(7), net.STOP_IDS
    ops = OpsConfig()
    for _ in range(300):
        inputs = [mk(s, rng.uniform(0, 400), rng.randint(0, 10), cap=rng.choice([45, 60, 75]), rt=rng.uniform(8, 35),
                     max_buses=rng.randint(6, 16), closed=rng.random() < 0.1) for s in ids]
        for s in inputs:
            s.buses = min(s.buses, s.max_buses)
        lead = rng.choice([0, 15, 30, 45, 60])
        res = optimise(inputs, ops, lead)
        _check_invariants(inputs, res, ops, lead)


def test_api_level_plan_is_advisory_and_consistent(svc):
    o = pipeline.optimise_plan(svc, OptimiseRequest(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=8, target_step=3))
    assert o.status == "advisory" and o.requires_human_approval and "human" in o.approval_notice.lower()
    assert all(c.satisfied for c in o.constraint_audit)
    assert sum(b.buses for b in o.before) == sum(a.buses for a in o.after)
    for r in o.recommendations:
        assert r.rationale and r.constraints and all(c.satisfied for c in r.constraints)
        assert r.travel_time_min <= o.lead_time_min - o.config_used["dispatch_buffer_min"]
