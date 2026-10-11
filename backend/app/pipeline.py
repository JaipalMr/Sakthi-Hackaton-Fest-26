"""PREDICT -> OPTIMISE orchestration used by the API routes, the simulator and the assistant tools."""
from __future__ import annotations

import pandas as pd

from backend.app.config import OpsConfig, Settings
from backend.app.data_store import DataStore
from backend.app.errors import ServiceError
from backend.app.model_service import ModelService
from backend.app.optimiser import StopInput, optimise
from backend.app.risk import LEVELS, assess
from backend.app.scenario import apply_scenario
from backend.app.schemas import (ForecastContext, ModelInfo, OptimiseRequest, OptimiseResponse, PredictResponse,
                                 Provenance, Scenario, SimulateRequest, SimulateResponse)
from ml import network as net

LIMITATIONS = [
    "Dataset and target labels are SYNTHETIC; accuracy figures describe synthetic data only.",
    "Weather, fleet plan, route times and closures for forecast slots are taken from the dataset as if forecast perfectly.",
    "Multi-step forecasts are recursive, so uncertainty grows with horizon; intervals are empirical and approximate.",
    "Crowd-risk levels use configurable operational assumptions, not universal safety thresholds.",
]
LEGEND = {
    "actual_input": "values read from the (synthetic) dataset: buses, weather, schedule, observed previous-slot counts",
    "model_prediction": "scikit-learn model output for future slots",
    "simulated_assumption": "values changed by the what-if scenario; hypothetical, not verified real-world outcomes",
    "actual_demand_synthetic": "synthetic target label kept for comparison; unavailable in scenarios",
}


class Services:
    def __init__(self, store: DataStore, model: ModelService, settings: Settings):
        self.store, self.model, self.settings = store, model, settings


def _validate_ids(ids: list[str] | None, label: str) -> None:
    bad = [i for i in (ids or []) if i not in net.STOP_IDS]
    if bad:
        raise ServiceError(422, f"Unknown {label}: {bad}. Valid stop ids: {net.STOP_IDS}", "unknown_stop")


def forecast_frame(svc: Services, ctx: ForecastContext, scenario: Scenario | None, min_steps: int = 1):
    """Predict ALL stops (optimiser needs the whole network); filtering happens when building responses."""
    svc.model.require()
    _validate_ids(ctx.stop_ids, "stop_ids")
    if scenario:
        _validate_ids(scenario.closed_stop_ids, "closed_stop_ids")
    steps = max(ctx.horizon_steps, min_steps)
    window, avail = svc.store.window(ctx.festival_id, pd.Timestamp(ctx.forecast_origin), steps)
    if avail < min_steps:
        raise ServiceError(422, f"Only {avail} forecast slot(s) remain after {ctx.forecast_origin.isoformat()} that day; "
                                f"{min_steps} requested. Choose an earlier origin.", "horizon_unavailable")
    warnings: list[str] = []
    if scenario and not scenario.is_baseline():
        window, warnings = apply_scenario(window, scenario, svc.store.rain_max)
    pred = svc.model.predict(window)
    ops = svc.settings.ops
    rows = []
    for sid, g in pred.sort_values(["stop_id", "step"]).groupby("stop_id"):
        stop = net.get_stop(sid)
        backlog = 0.0
        for _, r in g.iterrows():
            service = float(net.service_capacity(r["available_buses"], r["average_bus_capacity"], r["route_travel_time"]))
            a = assess(float(r["pred"]), service, backlog, stop.waiting_capacity, ops)
            backlog = a["projected_backlog"]
            rows.append({**r.to_dict(), "service_capacity": round(service, 1), **a})
    out = pd.DataFrame(rows)
    return out, avail, warnings


def _model_info(svc: Services, festival_id: str) -> ModelInfo:
    m = svc.model.metadata
    role = svc.model.role_of(festival_id)
    return ModelInfo(name=m["selected_model"], trained_at_utc=m["trained_at_utc"], festival_split_role=role,
                     in_sample=role in ("train", "validation"),
                     test_mae=round(m["test_one_step"]["mae"], 2), test_rmse=round(m["test_one_step"]["rmse"], 2),
                     baseline_persistence_test_mae=round(m["baselines"]["baseline_persistence"]["test"]["mae"], 2),
                     interval_method=m["interval_method"])


def totals(frame: pd.DataFrame, with_actual: bool) -> list[dict]:
    out = []
    for step, g in frame.groupby("step"):
        out.append(dict(step=int(step), timestamp=g["timestamp"].iloc[0].to_pydatetime(),
                        predicted_demand=round(float(g["pred"].sum()), 1),
                        actual_demand_synthetic=float(g["target_passenger_demand"].sum()) if with_actual else None,
                        service_capacity=round(float(g["service_capacity"].sum()), 1),
                        available_buses=int(g["available_buses"].sum())))
    return out


def predict(svc: Services, ctx: ForecastContext, scenario: Scenario | None = None) -> PredictResponse:
    frame, avail, warnings = forecast_frame(svc, ctx, scenario)
    frame = frame[frame["step"] <= ctx.horizon_steps]
    scen = scenario if scenario and not scenario.is_baseline() else None
    with_actual = scen is None
    wanted = ctx.stop_ids or net.STOP_IDS
    forecasts = []
    for sid in net.STOP_IDS:
        if sid not in wanted:
            continue
        stop, g = net.get_stop(sid), frame[frame["stop_id"] == sid].sort_values("step")
        steps = [dict(step=int(r.step), timestamp=r.timestamp.to_pydatetime(), predicted_demand=round(r.pred, 1),
                      interval_low=round(r.lo, 1), interval_high=round(r.hi, 1),
                      actual_demand_synthetic=float(r.target_passenger_demand) if with_actual else None,
                      available_buses=int(r.available_buses), average_bus_capacity=int(r.average_bus_capacity),
                      route_travel_time=float(r.route_travel_time), rainfall=float(r.rainfall),
                      route_closed=bool(r.route_closed), event_phase=str(r.event_phase),
                      minutes_to_event_end=float(r.minutes_to_end), service_capacity=r.service_capacity,
                      load_ratio=r.load_ratio, projected_backlog=r.projected_backlog,
                      crowding_ratio=r.crowding_ratio, risk_level=r.risk_level) for r in g.itertuples()]
        worst = max(steps, key=lambda s: (LEVELS.index(s["risk_level"]), s["load_ratio"]))
        forecasts.append(dict(stop_id=sid, stop_name=stop.stop_name, latitude=stop.latitude, longitude=stop.longitude,
                              role=stop.role, waiting_capacity=stop.waiting_capacity, steps=steps,
                              peak_risk_level=worst["risk_level"], peak_step=worst["step"],
                              total_predicted_demand=round(sum(s["predicted_demand"] for s in steps), 1)))
    if not forecasts:
        raise ServiceError(422, "No stops selected", "no_stops")
    sub = frame if ctx.stop_ids is None else frame[frame["stop_id"].isin(wanted)]
    return PredictResponse(
        festival_id=ctx.festival_id, festival_name=net.FESTIVAL_NAMES.get(ctx.festival_id, ctx.festival_id),
        forecast_origin=ctx.forecast_origin, horizon_steps_requested=ctx.horizon_steps,
        horizon_steps_returned=min(avail, ctx.horizon_steps), model=_model_info(svc, ctx.festival_id),
        provenance=Provenance(dataset="data/festival_transport_demand.csv (synthetic)", scenario_applied=scen is not None,
                              scenario=scen, legend=LEGEND, warnings=warnings),
        forecasts=forecasts, totals_by_step=totals(sub, with_actual), limitations=LIMITATIONS)


def _merge_ops(base: OpsConfig, over) -> OpsConfig:
    if not over:
        return base
    d = {k: v for k, v in over.model_dump().items() if v is not None}
    return OpsConfig(**{**base.__dict__, **d})


def optimise_plan(svc: Services, req: OptimiseRequest) -> OptimiseResponse:
    ctx = ForecastContext(festival_id=req.festival_id, forecast_origin=req.forecast_origin,
                          horizon_steps=max(req.horizon_steps, req.target_step), stop_ids=None)
    frame, avail, warnings = forecast_frame(svc, ctx, req.scenario, min_steps=req.target_step)
    ops = _merge_ops(svc.settings.ops, req.overrides)
    tgt = frame[frame["step"] == req.target_step].sort_values("stop_id")
    inputs = [StopInput(stop_id=r.stop_id, stop_name=net.get_stop(r.stop_id).stop_name, predicted_demand=float(r.pred),
                        buses=int(r.available_buses), avg_bus_capacity=float(r.average_bus_capacity),
                        route_travel_min=float(r.route_travel_time),
                        waiting_capacity=float(net.get_stop(r.stop_id).waiting_capacity),
                        max_buses=net.get_stop(r.stop_id).max_buses, closed=bool(r.route_closed),
                        backlog_in=float(frame[(frame.stop_id == r.stop_id) & (frame.step == req.target_step - 1)]["projected_backlog"].iloc[0])
                        if req.target_step > 1 else 0.0) for r in tgt.itertuples()]
    lead = (req.target_step - 1) * net.SLOT_MIN
    res = optimise(inputs, ops, lead)
    s = res["summary"]
    wanted = req.stop_ids
    return OptimiseResponse(
        festival_id=req.festival_id, forecast_origin=req.forecast_origin, target_step=req.target_step,
        target_timestamp=tgt["timestamp"].iloc[0].to_pydatetime(), lead_time_min=lead,
        approval_notice="ADVISORY ONLY - a human dispatcher must review and approve before any real bus is moved.",
        config_used=dict(reserve_margin=ops.reserve_margin, dispatch_buffer_min=ops.dispatch_buffer_min,
                         min_buses_per_stop=ops.min_buses_per_stop, max_moves=ops.max_moves,
                         load_elevated=ops.load_elevated, load_high=ops.load_high,
                         crowd_elevated=ops.crowd_elevated, crowd_high=ops.crowd_high),
        scenario_applied=bool(req.scenario and not req.scenario.is_baseline()),
        before=res["before"], after=res["after"], recommendations=res["recommendations"],
        unresolved=res["unresolved"], summary=s, constraint_audit=res["constraint_audit"],
        assumptions=["Allocation targets ONE forecast slot; buses are moved at most once (no chains).",
                     "A moved bus keeps its own vehicle capacity; loading rate at the destination follows the destination route time.",
                     "Safety/risk thresholds and margins are configurable operational assumptions, not universal limits.",
                     "Impact figures are model estimates on synthetic data, not measured outcomes.",
                     "Recommendations are advisory and require human approval before real dispatch."],
        warnings=warnings if not wanted else warnings)


def simulate(svc: Services, req: SimulateRequest) -> SimulateResponse:
    if req.scenario.is_baseline():
        raise ServiceError(422, "Scenario has no changes: adjust end-time shift, rainfall, bus availability or closures.", "empty_scenario")
    base_req = OptimiseRequest(festival_id=req.festival_id, forecast_origin=req.forecast_origin,
                               horizon_steps=req.horizon_steps, target_step=req.target_step, overrides=req.overrides)
    scen_req = base_req.model_copy(update={"scenario": req.scenario})
    ctx = ForecastContext(festival_id=req.festival_id, forecast_origin=req.forecast_origin,
                          horizon_steps=max(req.horizon_steps, req.target_step))
    bf, _, _ = forecast_frame(svc, ctx, None, min_steps=req.target_step)
    sf, _, warnings = forecast_frame(svc, ctx, req.scenario, min_steps=req.target_step)
    base_opt, scen_opt = optimise_plan(svc, base_req), optimise_plan(svc, scen_req)
    bt, st_ = bf[bf["step"] == req.target_step].set_index("stop_id"), sf[sf["step"] == req.target_step].set_index("stop_id")
    deltas = [dict(stop_id=sid, stop_name=net.get_stop(sid).stop_name,
                   baseline_demand=round(float(bt.loc[sid, "pred"]), 1), scenario_demand=round(float(st_.loc[sid, "pred"]), 1),
                   baseline_buses=int(bt.loc[sid, "available_buses"]), scenario_buses=int(st_.loc[sid, "available_buses"]),
                   baseline_risk=bt.loc[sid, "risk_level"], scenario_risk=st_.loc[sid, "risk_level"],
                   baseline_load_ratio=float(bt.loc[sid, "load_ratio"]), scenario_load_ratio=float(st_.loc[sid, "load_ratio"]))
              for sid in net.STOP_IDS]
    b, s = base_opt.summary, scen_opt.summary
    headline = dict(
        baseline_total_demand=round(float(bt["pred"].sum()), 1), scenario_total_demand=round(float(st_["pred"].sum()), 1),
        baseline_unserved_before_reallocation=b.unserved_before, scenario_unserved_before_reallocation=s.unserved_before,
        baseline_unserved_after_reallocation=b.unserved_after, scenario_unserved_after_reallocation=s.unserved_after,
        baseline_high_risk_stops=float(sum(d["baseline_risk"] == "high" for d in deltas)),
        scenario_high_risk_stops=float(sum(d["scenario_risk"] == "high" for d in deltas)),
        baseline_buses_moved=b.buses_moved, scenario_buses_moved=s.buses_moved)
    return SimulateResponse(
        festival_id=req.festival_id, forecast_origin=req.forecast_origin, target_step=req.target_step, scenario=req.scenario,
        labels=LEGEND | {"warning": "Scenario results are hypothetical model outputs under stated assumptions - not verified real-world outcomes."},
        warnings=warnings, baseline_totals=totals(bf[bf["step"] <= req.horizon_steps], True),
        scenario_totals=totals(sf[sf["step"] <= req.horizon_steps], False), stop_deltas=deltas,
        baseline_optimisation=base_opt, scenario_optimisation=scen_opt, headline=headline)
