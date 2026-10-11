"""CHAOS LAB - automated resilience stress-test ("chaos engineering for festival transport").

Runs a fixed battery of hypothetical disruptions (rain, schedule shifts, bus shortages, every single-stop closure and one
compound 'perfect storm') through the SAME forecast + optimiser pipeline, then scores how well the advised reallocation copes.
The score is a transparent heuristic over SYNTHETIC data - not a safety certification."""
from __future__ import annotations

from backend.app.pipeline import Services, optimise_plan, predict
from backend.app.schemas import (ChaosResult, ChaosResponse, ForecastContext, OptimiseRequest, Scenario)
from ml import network as net

BATTERY: list[tuple[str, str, str, dict, float]] = [  # id, category, label, scenario kwargs, weight
    ("rain5", "weather", "Light rain (5 mm/h)", dict(rainfall_mm_per_hr=5), 1),
    ("rain12", "weather", "Heavy rain (12 mm/h)", dict(rainfall_mm_per_hr=12), 1),
    ("rain20", "weather", "Storm (20 mm/h)", dict(rainfall_mm_per_hr=20), 1),
    ("late45", "schedule", "Festival overruns by 45 min", dict(festival_end_shift_min=45), 1),
    ("early45", "schedule", "Festival ends 45 min early", dict(festival_end_shift_min=-45), 1),
    ("fleet80", "fleet", "80% of buses available", dict(bus_availability_factor=0.8), 1),
    ("fleet60", "fleet", "60% of buses available", dict(bus_availability_factor=0.6), 1),
    ("fleet40", "fleet", "Driver strike: 40% of buses", dict(bus_availability_factor=0.4), 1),
    ("storm_combo", "compound", "Perfect storm: 15 mm/h + 60% buses + overrun", dict(rainfall_mm_per_hr=15, bus_availability_factor=0.6, festival_end_shift_min=30), 2),
]


def _grade(score: int) -> str:
    return "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"


_CACHE: dict[str, ChaosResponse] = {}


def _steps(horizon: int, target: int) -> list[int]:
    """A handful of slots spread across the window (+ the dispatcher's target slot): a scenario is judged on its WORST slot."""
    picks = {max(1, min(horizon, round(1 + i * (horizon - 1) / 3))) for i in range(4)} | {min(target, horizon)}
    return sorted(picks)


def run(svc: Services, ctx: ForecastContext, target_step: int) -> ChaosResponse:
    svc.model.require()
    key = f"{ctx.festival_id}|{ctx.forecast_origin.isoformat()}|{ctx.horizon_steps}|{target_step}"
    if key in _CACHE:
        return _CACHE[key]
    base_pred = predict(svc, ctx, None)
    horizon = base_pred.horizon_steps_returned
    steps = _steps(horizon, target_step)
    step_demand = {st: max(base_pred.totals_by_step[st - 1].predicted_demand, 1.0) for st in steps}
    time_of = {st: base_pred.totals_by_step[st - 1].timestamp.strftime("%H:%M") for st in steps}
    common = dict(festival_id=ctx.festival_id, forecast_origin=ctx.forecast_origin, horizon_steps=ctx.horizon_steps)
    base = {st: optimise_plan(svc, OptimiseRequest(**common, target_step=st)) for st in steps}
    tgt = min(target_step, horizon)

    cases = list(BATTERY) + [(f"close_{sid}", "closure", f"{net.get_stop(sid).stop_name} closed", dict(closed_stop_ids=[sid]), 1) for sid in net.STOP_IDS]
    results: list[ChaosResult] = []
    for cid, cat, label, kw, w in cases:
        scen = Scenario(**kw)
        worst = (0.0, 0.0, steps[0], 0.0, 0, 0)  # harm, extra, step, unserved, high_risk, moved
        for st in steps:
            o = optimise_plan(svc, OptimiseRequest(**common, target_step=st, scenario=scen))
            extra = max(0.0, o.summary.unserved_after - base[st].summary.unserved_after)
            harm = min(1.0, extra / step_demand[st])
            if harm > worst[0] or (harm == worst[0] == 0.0 and st == tgt):
                worst = (harm, extra, st, o.summary.unserved_after, o.summary.high_risk_stops_after, o.summary.buses_moved)
        harm, extra, st, uns, hr, mv = worst
        status = "critical" if harm >= 0.25 else "strained" if harm >= 0.08 else "coped"
        results.append(ChaosResult(id=cid, category=cat, label=label, weight=w, unserved_after=round(uns, 1), extra_unserved=round(extra, 1),
                                   harm=round(harm, 3), worst_time=time_of[st], high_risk_stops_after=hr, buses_moved=mv, status=status))
    wsum = sum(r.weight for r in results)
    score = int(round(100 * (1 - sum(r.harm * r.weight for r in results) / wsum)))
    closures = [r for r in results if r.category == "closure"]
    weakest = max(closures, key=lambda r: r.harm)
    worst = max(results, key=lambda r: r.harm)
    tips: list[str] = []
    if weakest.harm >= 0.08:
        tips.append(f"Single point of failure: {weakest.label.replace(' closed', '')}. Closing it leaves up to {weakest.extra_unserved:.0f} extra passengers unserved (around {weakest.worst_time}) - prepare a diversion plan and a standby bus.")
    for cat, text in (("fleet", "Fleet shortage is the biggest exposure - keep reserve vehicles or agreements with neighbouring operators."),
                      ("weather", "Rain pushes demand and travel times up - pre-brief drivers and stage buses earlier in wet forecasts."),
                      ("schedule", "Schedule shifts hurt timing - keep dispatchers able to re-run the plan 15 minutes before the finale.")):
        if worst.category == cat and worst.harm >= 0.08:
            tips.append(text)
    if worst.category == "compound" and worst.harm >= 0.08:
        tips.append("Overlapping disruptions compound each other - rehearse the 'perfect storm' playbook.")
    if not tips:
        tips.append("No scenario in the battery causes serious extra unserved demand for this slot; keep monitoring.")
    out = ChaosResponse(
        score=score, grade=_grade(score), slots_tested=[time_of[st] for st in steps],
        baseline_unserved_after=round(base[tgt].summary.unserved_after, 1), results=results, weakest_link=weakest, worst_case=worst, hardening_tips=tips,
        method=("Score = 100 x (1 - weighted mean harm). Harm = extra passengers left unserved after the advised reallocation versus the baseline plan, "
                "divided by predicted demand in that slot (capped at 1). Each scenario is judged on its WORST slot among the tested slots. Compound scenario weighs double."),
        narrative="", mode="demo", provider=None, model=None, disclaimer="Hypothetical scenarios on SYNTHETIC data; heuristic score, not a safety certification.")
    _CACHE[key] = out
    if len(_CACHE) > 64:
        _CACHE.pop(next(iter(_CACHE)))
    return out
