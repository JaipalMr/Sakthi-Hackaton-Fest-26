"""Tool layer for the GenAI assistant. Every tool calls BACKEND services (model, optimiser, simulator);
the LLM never produces numbers itself. Arguments are validated with Pydantic (extra fields forbidden) and
outputs are projected to compact, JSON-safe dicts built from validated response models."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.pipeline import Services, optimise_plan, predict, simulate
from backend.app.schemas import (AssistantContext, ForecastContext, OptimiseRequest, Scenario, SimulateRequest)
from ml import network as net


class StopDataArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stop_ids: list[str] | None = Field(None, max_length=10, description="subset of stop ids, e.g. ['S01']; omit for all")


class ForecastArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stop_ids: list[str] | None = Field(None, max_length=10)
    horizon_steps: int | None = Field(None, ge=1, le=12, description="number of 15-minute slots")


class RecommendArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_step: int | None = Field(None, ge=1, le=12, description="forecast step to allocate buses for")


class WhatIfArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    festival_end_shift_min: int = Field(0, ge=-60, le=60)
    rainfall_mm_per_hr: float | None = Field(None, ge=0, le=30)
    bus_availability_factor: float = Field(1.0, ge=0.0, le=1.5)
    closed_stop_ids: list[str] = Field(default_factory=list, max_length=10)
    target_step: int | None = Field(None, ge=1, le=12)


TOOL_SPECS = [
    dict(name="get_stop_data", model=StopDataArgs,
         description="Static facts about stops (names, role, waiting capacity, bay capacity, coordinates) plus the "
                     "buses currently planned at each stop for the first forecast slot."),
    dict(name="get_demand_forecast", model=ForecastArgs,
         description="Model-predicted passenger demand per stop and 15-minute step with uncertainty interval, service capacity "
                     "and crowd-risk level. Use for any question about expected crowds or risk."),
    dict(name="get_deployment_recommendations", model=RecommendArgs,
         description="Run the deterministic bus allocation optimiser. Returns advisory bus moves (origin, destination, count, "
                     "rationale, constraints, impact). Never invent bus moves yourself."),
    dict(name="run_what_if_simulation", model=WhatIfArgs,
         description="Simulate a scenario (festival end-time shift, rainfall, bus availability factor, closed stops) and "
                     "compare baseline vs scenario predictions and allocations."),
]


def tool_schemas() -> list[dict]:
    return [dict(name=t["name"], description=t["description"], input_schema=t["model"].model_json_schema()) for t in TOOL_SPECS]


def _ctx(c: AssistantContext, **kw) -> dict:
    return dict(festival_id=c.festival_id, forecast_origin=c.forecast_origin, **kw)


def run_tool(svc: Services, name: str, raw_args: dict, ctx: AssistantContext) -> dict[str, Any]:
    """Validate args, call the backend, return a compact JSON-safe dict. Raises ValueError on bad args."""
    spec = next((t for t in TOOL_SPECS if t["name"] == name), None)
    if spec is None:
        raise ValueError(f"unknown tool '{name}'")
    try:
        args = spec["model"].model_validate(raw_args or {})
    except ValidationError as e:
        raise ValueError("invalid arguments: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))
    bad = [s for s in (getattr(args, "stop_ids", None) or []) + (getattr(args, "closed_stop_ids", None) or []) if s not in net.STOP_IDS]
    if bad:
        raise ValueError(f"unknown stop ids {bad}; valid ids: {net.STOP_IDS}")

    if name == "get_stop_data":
        r = predict(svc, ForecastContext(**_ctx(ctx, horizon_steps=1, stop_ids=args.stop_ids)), ctx.scenario)
        return dict(source="backend: dataset + planned fleet at first forecast slot",
                    stops=[dict(stop_id=f.stop_id, name=f.stop_name, role=f.role, waiting_capacity=f.waiting_capacity,
                                buses_planned=f.steps[0].available_buses, route_closed=f.steps[0].route_closed,
                                service_capacity=f.steps[0].service_capacity) for f in r.forecasts])
    if name == "get_demand_forecast":
        h = args.horizon_steps or ctx.horizon_steps
        r = predict(svc, ForecastContext(**_ctx(ctx, horizon_steps=h, stop_ids=args.stop_ids)), ctx.scenario)
        return dict(source="backend: scikit-learn model on SYNTHETIC data", scenario_applied=r.provenance.scenario_applied,
                    steps_returned=r.horizon_steps_returned, model_test_mae=r.model.test_mae,
                    festival_split_role=r.model.festival_split_role,
                    totals=[dict(step=t.step, time=t.timestamp.strftime("%H:%M"), predicted=t.predicted_demand,
                                 service_capacity=t.service_capacity) for t in r.totals_by_step],
                    stops=[dict(stop_id=f.stop_id, name=f.stop_name, total_predicted=f.total_predicted_demand,
                                peak_risk=f.peak_risk_level, peak_step=f.peak_step,
                                peak_step_demand=next(s.predicted_demand for s in f.steps if s.step == f.peak_step),
                                peak_step_interval=[next(s.interval_low for s in f.steps if s.step == f.peak_step),
                                                    next(s.interval_high for s in f.steps if s.step == f.peak_step)],
                                peak_step_service=next(s.service_capacity for s in f.steps if s.step == f.peak_step))
                           for f in r.forecasts], limitations=r.limitations[:2])
    if name == "get_deployment_recommendations":
        o = optimise_plan(svc, OptimiseRequest(**_ctx(ctx, horizon_steps=ctx.horizon_steps, target_step=args.target_step or ctx.target_step,
                                                      scenario=ctx.scenario)))
        return _opt_summary(o)
    if name == "run_what_if_simulation":
        sc = Scenario(festival_end_shift_min=args.festival_end_shift_min, rainfall_mm_per_hr=args.rainfall_mm_per_hr,
                      bus_availability_factor=args.bus_availability_factor, closed_stop_ids=args.closed_stop_ids)
        s = simulate(svc, SimulateRequest(**_ctx(ctx, horizon_steps=ctx.horizon_steps, target_step=args.target_step or ctx.target_step), scenario=sc))
        return dict(source="backend: simulation (hypothetical assumptions, not real outcomes)",
                    scenario=sc.model_dump(), headline=s.headline, warnings=s.warnings,
                    baseline_recommendations=_opt_summary(s.baseline_optimisation)["recommendations"],
                    scenario_recommendations=_opt_summary(s.scenario_optimisation)["recommendations"],
                    changed_risk_stops=[dict(stop=d.stop_name, baseline=d.baseline_risk, scenario=d.scenario_risk,
                                             baseline_demand=d.baseline_demand, scenario_demand=d.scenario_demand)
                                        for d in s.stop_deltas if d.baseline_risk != d.scenario_risk or abs(d.baseline_demand - d.scenario_demand) >= 20])
    raise ValueError(f"unhandled tool {name}")


def _opt_summary(o) -> dict:
    return dict(source="backend: deterministic optimiser (advisory; requires human approval)", target_time=o.target_timestamp.strftime("%H:%M"),
                lead_time_min=o.lead_time_min, summary=o.summary.model_dump(),
                recommendations=[dict(from_stop=r.origin_stop_name, to_stop=r.destination_stop_name, buses=r.buses,
                                      travel_min=r.travel_time_min, net_passengers_served=r.estimated_impact["net_passengers_served"])
                                 for r in o.recommendations],
                unresolved=[dict(stop=u.stop_name, remaining_unserved=u.remaining_unserved, reason=u.reason) for u in o.unresolved],
                constraints_all_satisfied=all(c.satisfied for c in o.constraint_audit))


def to_json(obj: Any) -> str:
    return json.dumps(obj, default=str)
