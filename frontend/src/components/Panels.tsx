import { useEffect, useRef, useState } from "react";
import type { AssistantResponse, MetricsResponse, OptimiseResponse, PredictResponse, SimulateResponse, StopForecast } from "../types";
import { RISK_GLYPH, RISK_LABEL, RISK_ORDER, hhmm, num, pct } from "../format";
import { Empty, Tag } from "./States";
import LineChart from "./LineChart";
import { canListen, listen } from "../speech";

export function RiskBadge({ level }: { level: "low" | "elevated" | "high" }) {
  return <span className={`risk risk-${level}`}><span aria-hidden>{RISK_GLYPH[level]}</span> {RISK_LABEL[level]}</span>;
}

export function Kpis({ predict, plan, metrics, targetStep }: { predict: PredictResponse; plan: OptimiseResponse | null; metrics: MetricsResponse | null; targetStep: number }) {
  const t = predict.totals_by_step;
  const total = t.reduce((a, s) => a + s.predicted_demand, 0);
  const peak = t.reduce((a, s) => (s.predicted_demand > a.predicted_demand ? s : a), t[0]);
  const buses = t[0]?.available_buses ?? 0;
  const items: { k: string; v: string; s: string }[] = [
    { k: "Predicted passengers", v: num(total), s: `next ${predict.horizon_steps_returned} slots, all stops` },
    { k: "Busiest slot", v: hhmm(peak.timestamp), s: `${num(peak.predicted_demand)} passengers predicted` },
    { k: "High-risk stops", v: plan ? `${plan.summary.high_risk_stops_before} → ${plan.summary.high_risk_stops_after}` : "–", s: `at +${(targetStep - 1) * 15} min, before → after advised moves` },
    { k: "Unserved passengers", v: plan ? `${num(plan.summary.unserved_before)} → ${num(plan.summary.unserved_after)}` : "–", s: "at target slot, before → after (estimate)" },
    { k: "Buses planned", v: num(buses), s: "across all stops, first slot" },
    { k: "Model error (test MAE)", v: metrics ? `${metrics.model.test_one_step.mae.toFixed(1)}` : "–", s: metrics ? `passengers/stop-slot; persistence ${metrics.model.baselines.baseline_persistence.test.mae.toFixed(1)}` : "" },
  ];
  return <dl className="kpis">{items.map((i) => <div key={i.k}><dt>{i.k}</dt><dd>{i.v}</dd><small>{i.s}</small></div>)}</dl>;
}

export function ForecastView({ predict, stopId }: { predict: PredictResponse; stopId: string | null }) {
  const f: StopForecast | undefined = stopId ? predict.forecasts.find((x) => x.stop_id === stopId) : undefined;
  const labels = predict.totals_by_step.map((s) => hhmm(s.timestamp));
  const steps = f?.steps;
  const cap = steps ? steps.map((s) => s.service_capacity) : predict.totals_by_step.map((s) => s.service_capacity);
  const pred = steps ? steps.map((s) => s.predicted_demand) : predict.totals_by_step.map((s) => s.predicted_demand);
  const act = steps ? steps.map((s) => s.actual_demand_synthetic) : predict.totals_by_step.map((s) => s.actual_demand_synthetic);
  const hasActual = act.some((v) => v !== null);
  return (
    <>
      <LineChart title={`Forecast demand ${f ? f.stop_name : "all stops"}`} labels={labels}
        series={[{ key: "p", label: "Model prediction", color: "#0B7A75", values: pred }, { key: "c", label: "Service capacity (planned buses)", color: "#14262C", dash: "5 4", values: cap }]}
        band={f ? { low: f.steps.map((s) => s.interval_low), high: f.steps.map((s) => s.interval_high), label: "80% interval (empirical)" } : undefined}
        dots={hasActual ? { key: "a", label: "Actual", color: "#C2362B", values: act } : undefined} />
      {!f && <p className="hint">Select a stop (filter or map) to see its uncertainty interval.</p>}
      {predict.model.in_sample && <p className="hint warn">This festival was in the model's training/validation data, so predictions look better than they would on a new event. Pick the held-out test festival for an honest view.</p>}
    </>
  );
}

export function StopTable({ predict, plan, targetStep, stopId, risk, onSelect }: { predict: PredictResponse; plan: OptimiseResponse | null; targetStep: number; stopId: string | null; risk: "all" | "elevated" | "high"; onSelect: (id: string | null) => void }) {
  const after = new Map(plan?.after.map((a) => [a.stop_id, a]));
  const rows = predict.forecasts
    .map((f) => ({ f, s: f.steps[targetStep - 1] }))
    .filter((r) => r.s && (!stopId || r.f.stop_id === stopId) && (risk === "all" || RISK_ORDER[r.s.risk_level] >= (risk === "high" ? 2 : 1)))
    .sort((a, b) => RISK_ORDER[b.s.risk_level] - RISK_ORDER[a.s.risk_level] || b.s.load_ratio - a.s.load_ratio);
  if (!rows.length) return <Empty>No stops match the current filters. Clear the stop or risk filter to see all stops.</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Stop</th><th className="n">Predicted</th><th className="n">80% range</th><th className="n">Buses</th><th className="n">Capacity</th><th className="n">Load</th><th>Risk</th><th className="n">Buses after</th><th>Risk after</th></tr></thead>
        <tbody>
          {rows.map(({ f, s }) => {
            const a = after.get(f.stop_id);
            return (
              <tr key={f.stop_id} className={stopId === f.stop_id ? "sel" : ""} onClick={() => onSelect(stopId === f.stop_id ? null : f.stop_id)}>
                <th scope="row">{f.stop_name}<small>{f.stop_id}{s.route_closed ? " · route closed" : ""}</small></th>
                <td className="n">{num(s.predicted_demand)}</td><td className="n">{num(s.interval_low)}–{num(s.interval_high)}</td>
                <td className="n">{s.available_buses}</td><td className="n">{num(s.service_capacity)}</td><td className="n">{s.load_ratio.toFixed(2)}</td>
                <td><RiskBadge level={s.risk_level} /></td>
                <td className="n">{a ? a.buses : "–"}{a && a.buses !== s.available_buses ? <b className={a.buses > s.available_buses ? "up" : "down"}> {a.buses > s.available_buses ? "+" : "−"}{Math.abs(a.buses - s.available_buses)}</b> : null}</td>
                <td>{a ? <RiskBadge level={a.risk_level} /> : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Recommendations({ plan }: { plan: OptimiseResponse }) {
  const passed = plan.constraint_audit.filter((c) => c.satisfied).length;
  return (
    <>
      <div className="advisory" role="note">{plan.approval_notice}</div>
      <p className="summary-line">
        Slot {hhmm(plan.target_timestamp)} (lead time {plan.lead_time_min} min): {plan.summary.buses_moved} bus move{plan.summary.buses_moved === 1 ? "" : "s"} · unserved {num(plan.summary.unserved_before)} → {num(plan.summary.unserved_after)} · service coverage {pct(plan.summary.served_share_before)} → {pct(plan.summary.served_share_after)} · constraints {passed}/{plan.constraint_audit.length} passed
      </p>
      {plan.recommendations.length === 0 ? <Empty>No bus moves recommended for this slot. {plan.unresolved[0]?.reason ?? "Current allocation already covers predicted demand."}</Empty> : (
        <ol className="recs">
          {plan.recommendations.map((r) => (
            <li key={r.rank}>
              <div className="rec-head"><b>{r.buses} bus{r.buses > 1 ? "es" : ""}</b> {r.origin_stop_name} <span aria-hidden>→</span><span className="sr-only"> to </span> {r.destination_stop_name}<span className="rec-meta">{num(r.travel_time_min)} min · +{num(r.estimated_impact.net_passengers_served, 1)} passengers served (est.)</span></div>
              <p>{r.rationale}</p>
              <details><summary>Constraints checked ({r.constraints.filter((c) => c.satisfied).length}/{r.constraints.length})</summary>
                <ul>{r.constraints.map((c) => <li key={c.name}>{c.satisfied ? "✓" : "✗"} {c.name}: {c.detail}</li>)}</ul></details>
            </li>
          ))}
        </ol>
      )}
      {plan.unresolved.length > 0 && <details className="unresolved"><summary>Still short after reallocation ({plan.unresolved.length})</summary><ul>{plan.unresolved.map((u) => <li key={u.stop_id}>{u.stop_name}: {num(u.remaining_unserved)} unserved — {u.reason}</li>)}</ul></details>}
      <details><summary>Assumptions and limits</summary><ul>{plan.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></details>
    </>
  );
}

export function SimulationView({ sim }: { sim: SimulateResponse }) {
  const h = sim.headline;
  const labels = sim.baseline_totals.map((s) => hhmm(s.timestamp));
  const rows: [string, number, number][] = [
    ["Total predicted demand (target slot)", h.baseline_total_demand, h.scenario_total_demand],
    ["Unserved before reallocation", h.baseline_unserved_before_reallocation, h.scenario_unserved_before_reallocation],
    ["Unserved after advised moves", h.baseline_unserved_after_reallocation, h.scenario_unserved_after_reallocation],
    ["High-risk stops", h.baseline_high_risk_stops, h.scenario_high_risk_stops],
    ["Buses advised to move", h.baseline_buses_moved, h.scenario_buses_moved],
  ];
  return (
    <>
      <p className="legend-tags"><Tag kind="input">Actual input data</Tag> <Tag kind="model">Model prediction</Tag> <Tag kind="sim">Simulated assumption</Tag></p>
      <div className="sim-warning" role="note">{sim.labels.warning}</div>
      {sim.warnings.map((w) => <p key={w} className="hint warn">{w}</p>)}
      <LineChart title="Baseline versus scenario total demand" labels={labels} unit="total passengers per 15 min"
        series={[{ key: "b", label: "Baseline prediction", color: "#0B7A75", values: sim.baseline_totals.map((t) => t.predicted_demand) },
                 { key: "s", label: "Scenario (simulated)", color: "#B4560A", dash: "6 3", values: sim.scenario_totals.map((t) => t.predicted_demand) }]} />
      <div className="table-wrap"><table><thead><tr><th>Measure</th><th className="n">Baseline</th><th className="n">Scenario (simulated)</th><th className="n">Change</th></tr></thead>
        <tbody>{rows.map(([k, b, s]) => <tr key={k}><th scope="row">{k}</th><td className="n">{num(b, 0)}</td><td className="n">{num(s, 0)}</td><td className={`n ${s > b ? "up" : s < b ? "down" : ""}`}>{s - b > 0 ? "+" : ""}{num(s - b, 0)}</td></tr>)}</tbody></table></div>
      <div className="table-wrap"><table><thead><tr><th>Stop</th><th className="n">Demand base</th><th className="n">Demand scenario</th><th className="n">Buses base</th><th className="n">Buses scenario</th><th>Risk base</th><th>Risk scenario</th></tr></thead>
        <tbody>{sim.stop_deltas.map((d) => <tr key={d.stop_id}><th scope="row">{d.stop_name}</th><td className="n">{num(d.baseline_demand)}</td><td className="n">{num(d.scenario_demand)}</td><td className="n">{d.baseline_buses}</td><td className="n">{d.scenario_buses}</td><td><RiskBadge level={d.baseline_risk} /></td><td><RiskBadge level={d.scenario_risk} /></td></tr>)}</tbody></table></div>
    </>
  );
}

export function Assistant({ onAsk, history, busy, error, includeScenario, setIncludeScenario, scenarioActive }: {
  onAsk: (m: string) => void; history: { role: "user" | "assistant"; text: string; meta?: AssistantResponse }[]; busy: boolean; error: string | null;
  includeScenario: boolean; setIncludeScenario: (b: boolean) => void; scenarioActive: boolean;
}) {
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const [mic, setMic] = useState(false);
  const stopMic = useRef<() => void>(() => {});
  const toggleMic = () => {
    if (mic) { stopMic.current(); return; }
    setMic(true);
    stopMic.current = listen((t) => send(t), () => setMic(false));
  };
  useEffect(() => { endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }); }, [history.length, busy]);
  const quick = ["Which stops are at highest risk?", "Where should buses move?", "What if it rains 12 mm/h and the festival ends 30 minutes later?"];
  const send = (m: string) => { if (m.trim() && !busy) { onAsk(m.trim()); setText(""); } };
  return (
    <div className="assistant">
      <div className="chat" aria-live="polite">
        {history.length === 0 && (
          <div className="chat-welcome">
            <div className="avatar avatar-ai" aria-hidden>✦</div>
            <p>Hi! I explain what the forecast model, optimiser and simulator say. Ask me anything about the current window - I will call the backend tools and never make up numbers.</p>
          </div>
        )}
        {history.map((m, i) => (
          <div key={i} className={`msg-row msg-row-${m.role}`}>
            <div className={`avatar avatar-${m.role === "user" ? "user" : "ai"}`} aria-hidden>{m.role === "user" ? "You" : "✦"}</div>
            <div className={`msg msg-${m.role}`}>
              {m.meta && <div className="msg-meta">
                {m.meta.mode === "live_llm" ? <Tag kind="model">Live LLM · {m.meta.provider}/{m.meta.model}</Tag> : <Tag kind="sim">Demo mode · rule-based, not an LLM</Tag>}
                {m.meta.tool_calls.map((t, j) => <span key={j} className={`toolchip ${t.ok ? "" : "bad"}`}>{t.ok ? "used" : "rejected"} {t.name}</span>)}
              </div>}
              <p>{m.text}</p>
              {m.meta?.fallback_reason && <p className="hint warn">Fallback: {m.meta.fallback_reason}</p>}
              {m.meta?.warnings.map((w) => <p key={w} className="hint warn">{w}</p>)}
            </div>
          </div>
        ))}
        {busy && <div className="msg-row"><div className="avatar avatar-ai" aria-hidden>✦</div><div className="msg msg-assistant typing" role="status"><span /><span /><span /><em className="sr-only">Asking the backend…</em></div></div>}
        {error && <div className="state state-error" role="alert">{error}</div>}
        <div ref={endRef} />
      </div>
      <div className="quick">{quick.map((q) => <button key={q} className="chip-suggest" disabled={busy} onClick={() => send(q)}>{q}</button>)}</div>
      <label className="check"><input type="checkbox" checked={includeScenario} disabled={!scenarioActive} onChange={(e) => setIncludeScenario(e.target.checked)} />Use current what-if in answers{!scenarioActive && " (set one first)"}</label>
      <form onSubmit={(e) => { e.preventDefault(); send(text); }} className="ask">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about stops, risk or buses" aria-label="Message to assistant" maxLength={2000} />
        {canListen() && <button type="button" className={`btn btn-mic ${mic ? "on" : ""}`} onClick={toggleMic} disabled={busy} aria-label={mic ? "Stop listening" : "Ask by voice"} title="Ask by voice">{mic ? "◼" : "🎙"}</button>}
        <button className="btn btn-primary" disabled={busy || !text.trim()}>Send</button>
      </form>
      <p className="hint">The assistant explains backend results. It cannot dispatch buses; all recommendations need human approval.</p>
    </div>
  );
}
