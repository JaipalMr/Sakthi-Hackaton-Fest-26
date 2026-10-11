import { useEffect, useMemo, useRef, useState } from "react";
import { API_LABEL, api, ApiError } from "./api/client";
import { useRemote } from "./hooks";
import type { AnnouncementResponse, AssistantResponse, BriefingResponse, ChaosResponse, Health, LangCode, Scenario, SimulateResponse } from "./types";
import { BASELINE, isBaseline } from "./types";
import { cleanName, hhmm } from "./format";
import { Empty, ErrorBox, Loading, Panel, Tag } from "./components/States";
import Filters, { type FilterState } from "./components/Filters";
import WhatIf from "./components/WhatIf";
import NetworkMap from "./components/NetworkMap";
import Briefing from "./components/Briefing";
import ChaosLab from "./components/ChaosLab";
import TimeMachine from "./components/TimeMachine";
import Announcements from "./components/Announcements";
import DispatchDesk, { type Order } from "./components/DispatchDesk";
import { Assistant, ForecastView, Kpis, Recommendations, SimulationView, StopTable } from "./components/Panels";
import { RISK_ORDER } from "./format";

type Conn = { state: "checking" | "connected" | "degraded" | "offline"; health: Health | null; error?: string };

/** Polls /api/health. Checks every 15 s while connected but every 3 s while offline, so the page recovers on its own
 *  as soon as the backend is started (no manual refresh needed). */
function useConnection(nonce: number): Conn {
  const [c, setC] = useState<Conn>({ state: "checking", health: null });
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    const tick = () => api.health()
      .then((h) => { if (!alive) return; setC({ state: h.status === "ok" ? "connected" : "degraded", health: h }); timer = setTimeout(tick, 15000); })
      .catch((e: Error) => { if (!alive) return; setC({ state: "offline", health: null, error: e.message }); timer = setTimeout(tick, 3000); });
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [nonce]);
  return c;
}

export default function App() {
  const [nonce, setNonce] = useState(0);
  const retry = () => setNonce((n) => n + 1);
  const conn = useConnection(nonce);
  // Backend (re)appeared after being offline: reload every section automatically.
  const wasOffline = useRef(false);
  useEffect(() => {
    if (conn.state === "offline") wasOffline.current = true;
    else if ((conn.state === "connected" || conn.state === "degraded") && wasOffline.current) { wasOffline.current = false; retry(); }
  }, [conn.state]);  // eslint-disable-line react-hooks/exhaustive-deps
  const festivals = useRemote((s) => api.festivals(s), [nonce]);
  const stops = useRemote((s) => api.stops(s), [nonce]);
  const metrics = useRemote((s) => api.metrics(s), [nonce]);

  const [f, setF] = useState<FilterState | null>(null);
  useEffect(() => {  // default: held-out test festival, day 4, 30 min before scheduled end
    if (!festivals.data || f) return;
    const fest = festivals.data.festivals.find((x) => x.split_role === "test") ?? festivals.data.festivals[0];
    const dayIdx = Math.min(3, fest.days.length - 1), day = fest.days[dayIdx];
    const [eh, em] = day.scheduled_end.split(":").map(Number);
    const target = eh * 60 + em - 30;
    const idx = day.slots.findIndex((s) => Number(s.slice(11, 13)) * 60 + Number(s.slice(14, 16)) === target);
    setF({ festivalId: fest.festival_id, dayIdx, slotIdx: Math.max(idx, 0), horizon: 8, targetStep: 3, stopId: null, risk: "all" });
  }, [festivals.data, f]);

  const fest = festivals.data?.festivals.find((x) => x.festival_id === f?.festivalId);
  const origin = fest && f ? fest.days[Math.min(f.dayIdx, fest.days.length - 1)].slots[Math.min(f.slotIdx, 49)] : null;
  const params = origin && f ? { festival_id: f.festivalId, forecast_origin: origin, horizon_steps: f.horizon } : null;

  const predict = useRemote(params ? (s) => api.predict(params, s) : null, [params?.festival_id, params?.forecast_origin, params?.horizon_steps, nonce]);
  const maxStep = predict.data?.horizon_steps_returned ?? f?.horizon ?? 1;
  const step = f ? Math.min(f.targetStep, maxStep) : 1;
  const plan = useRemote(params && predict.data ? (s) => api.optimise({ ...params, target_step: step }, s) : null,
    [params?.festival_id, params?.forecast_origin, params?.horizon_steps, step, predict.data?.horizon_steps_returned, nonce]);

  const [scenario, setScenario] = useState<Scenario>(BASELINE);
  const [sim, setSim] = useState<{ data: SimulateResponse | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: false });
  useEffect(() => setSim({ data: null, error: null, loading: false }), [params?.festival_id, params?.forecast_origin, params?.horizon_steps, step]);
  const runSim = () => {
    if (!params) return;
    setSim({ data: null, error: null, loading: true });
    api.simulate({ ...params, target_step: step, scenario }).then((data) => setSim({ data, error: null, loading: false }))
      .catch((e: Error) => setSim({ data: null, error: e.message, loading: false }));
  };

  const [chat, setChat] = useState<{ role: "user" | "assistant"; text: string; meta?: AssistantResponse }[]>([]);
  const [busy, setBusy] = useState(false); const [chatErr, setChatErr] = useState<string | null>(null);
  const [useScenario, setUseScenario] = useState(false);
  const ask = (message: string) => {
    if (!params) return;
    setChat((c) => [...c, { role: "user", text: message }]); setBusy(true); setChatErr(null);
    api.assistant({ message, history: chat.slice(-8).map((m) => ({ role: m.role, content: m.text })),
      context: { ...params, target_step: step, scenario: useScenario && !isBaseline(scenario) ? scenario : null } })
      .then((r) => setChat((c) => [...c, { role: "assistant", text: r.answer, meta: r }]))
      .catch((e: ApiError) => setChatErr(e.message)).finally(() => setBusy(false));
  };

  const [brief, setBrief] = useState<{ data: BriefingResponse | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: false });
  useEffect(() => setBrief({ data: null, error: null, loading: false }), [params?.festival_id, params?.forecast_origin, params?.horizon_steps, step]);
  const genBrief = () => {
    if (!params) return;
    setBrief({ data: null, error: null, loading: true });
    api.briefing({ context: { ...params, target_step: step, scenario: useScenario && !isBaseline(scenario) ? scenario : null } })
      .then((data) => setBrief({ data, error: null, loading: false }))
      .catch((e: Error) => setBrief({ data: null, error: e.message, loading: false }));
  };

  const ctxFor = () => ({ ...params!, target_step: step, scenario: useScenario && !isBaseline(scenario) ? scenario : null });
  const [chaos, setChaos] = useState<{ data: ChaosResponse | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: false });
  const [pa, setPa] = useState<{ data: AnnouncementResponse | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: false });
  useEffect(() => { setChaos({ data: null, error: null, loading: false }); setPa({ data: null, error: null, loading: false }); }, [params?.festival_id, params?.forecast_origin, params?.horizon_steps, step]);
  const runChaos = () => {
    if (!params) return;
    setChaos({ data: null, error: null, loading: true });
    api.chaos({ context: { ...params, target_step: step, scenario: null } }).then((data) => setChaos({ data, error: null, loading: false }))
      .catch((e: Error) => setChaos({ data: null, error: e.message, loading: false }));
  };
  const genPa = (languages: LangCode[]) => {
    if (!params) return;
    setPa({ data: null, error: null, loading: true });
    api.announcements({ context: ctxFor(), languages }).then((data) => setPa({ data, error: null, loading: false }))
      .catch((e: Error) => setPa({ data: null, error: e.message, loading: false }));
  };
  // Time machine: the map can show any forecast slot; advised moves are only drawn for the allocation slot.
  const [viewStepRaw, setViewStep] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const viewStep = Math.min(viewStepRaw ?? step, maxStep);
  useEffect(() => { setViewStep(null); setPlaying(false); }, [params?.festival_id, params?.forecast_origin, params?.horizon_steps, step]);
  // Dispatch desk audit log
  const [orders, setOrders] = useState<Order[]>([]);
  const decide = (o: Omit<Order, "id" | "at">) => setOrders((l) => [...l, { ...o, id: `DSP-${String(l.length + 1).padStart(3, "0")}`, at: new Date().toLocaleTimeString() }]);

  const dim = useMemo(() => {
    const s = new Set<string>();
    if (!predict.data || !f) return s;
    for (const fc of predict.data.forecasts) { const st = fc.steps[viewStep - 1]; if (st && f.risk !== "all" && RISK_ORDER[st.risk_level] < (f.risk === "high" ? 2 : 1)) s.add(fc.stop_id); }
    return s;
  }, [predict.data, f, viewStep]);

  const pill = { checking: "Connecting…", connected: "API connected", degraded: "API degraded", offline: "API offline" }[conn.state];
  const fatal = festivals.error || stops.error;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><span className="logo" aria-hidden>◈</span><div><h1>Festival Transport Command</h1><p>Predict · Optimise · Explain · Simulate</p></div></div>
        <div className="top-status">
          <span className={`pill pill-${conn.state}`} title={conn.error ?? API_LABEL}><i aria-hidden />{pill}</span>
          {conn.health && <span className="pill pill-neutral">{conn.health.model_loaded ? "Model loaded" : "Model missing"}</span>}
          {conn.health && <span className="pill pill-neutral">{conn.health.llm_mode === "live" ? `Assistant: live ${conn.health.llm_provider}` : "Assistant: demo mode"}</span>}
        </div>
      </header>
      {conn.state === "offline" && <div className="banner" role="alert">Cannot reach the backend at <code>{API_LABEL}</code>. Start it from the repository root with <code>python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000</code> (or run <code>run_windows.bat</code> / <code>./run.sh</code>). The first start can take about a minute while the model is prepared. Retrying automatically every few seconds - or <button className="btn btn-quiet" onClick={retry}>retry now</button>.</div>}
      {conn.state === "degraded" && conn.health && <div className="banner" role="alert">Backend is degraded: {conn.health.details.join(" ")}</div>}
      <main className="grid">
        <div className="rail-col rail-col-left">
        <aside className="rail rail-left">
          <Panel title="Forecast window" id="filters">
            {festivals.loading && !festivals.data ? <Loading label="Loading festivals…" /> : fatal ? <ErrorBox message={fatal} onRetry={retry} /> :
              festivals.data && stops.data && f ? <Filters festivals={festivals.data.festivals} stops={stops.data.stops} value={f} maxStep={maxStep} onChange={setF} /> : <Empty>No festivals available.</Empty>}
          </Panel>
          <Panel title="What-if simulation" id="whatif">
            {stops.data ? <WhatIf value={scenario} stops={stops.data.stops} onChange={setScenario} onRun={runSim} running={sim.loading} /> : <Loading />}
          </Panel>
        </aside>
        </div>
        <div className="center">
          {predict.error ? <ErrorBox message={predict.error} onRetry={retry} /> : !predict.data ? <Loading label="Running forecast…" /> : (
            <>
              <Panel title={cleanName(predict.data.festival_name)} note={<>Forecast from {origin && hhmm(origin)}, {predict.data.horizon_steps_returned} slots. <Tag kind="input">dataset inputs</Tag> <Tag kind="model">model prediction</Tag></>}>
                <Kpis predict={predict.data} plan={plan.data} metrics={metrics.data} targetStep={step} />
              </Panel>
              <Panel title="AI shift briefing" note="Plain-language summary of this window" id="briefing" actions={<Tag kind="advisory">advisory</Tag>}>
                <Briefing data={brief.data} loading={brief.loading} error={brief.error} onGenerate={genBrief}
                  liveLabel={conn.health?.llm_mode === "live" ? `${conn.health.llm_provider}${conn.health.llm_model ? ` / ${conn.health.llm_model}` : ""}` : null} />
              </Panel>
              <Panel title="Demand forecast" note={f?.stopId ? stops.data?.stops.find((s) => s.stop_id === f.stopId)?.stop_name : "All stops combined"} actions={predict.loading ? <span className="spinner" aria-label="Refreshing" /> : undefined}>
                <ForecastView predict={predict.data} stopId={f?.stopId ?? null} />
              </Panel>
              <div className="stack">
                <Panel title="Network view · Time Machine" note={viewStep === step ? "Click a stop to filter · press play to watch the crowd move" : "Previewing another slot - advised moves are shown only at the allocation slot"}>
                  <TimeMachine predict={predict.data} viewStep={viewStep} allocStep={step} playing={playing} setPlaying={setPlaying} setViewStep={setViewStep} />
                  {stops.data && f ? <NetworkMap stops={stops.data} forecasts={predict.data.forecasts} targetStep={viewStep} plan={viewStep === step ? plan.data : null} selected={f.stopId} onSelect={(id) => setF({ ...f, stopId: id })} dim={dim} /> : <Loading />}
                </Panel>
                <Panel title="Deployment recommendations" note="From the deterministic allocation engine">
                  {plan.error ? <ErrorBox message={plan.error} onRetry={retry} /> : !plan.data ? <Loading label="Optimising…" /> : <Recommendations plan={plan.data} />}
                </Panel>
              </div>
              <Panel title="Dispatch desk" note="Human approval workflow with audit trail" id="desk" actions={<Tag kind="advisory">human in the loop</Tag>}>
                <DispatchDesk plan={plan.data} festival={cleanName(predict.data.festival_name)} orders={orders} onDecide={decide} />
              </Panel>
              <Panel title="Chaos Lab" note="Automated resilience stress-test" id="chaos" actions={<Tag kind="sim">hypothetical</Tag>}>
                <ChaosLab data={chaos.data} loading={chaos.loading} error={chaos.error} onRun={runChaos} />
              </Panel>
              <Panel title="Passenger announcements" note="Multilingual PA drafts with voice playback" id="pa">
                <Announcements data={pa.data} loading={pa.loading} error={pa.error} onGenerate={genPa} />
              </Panel>
              <Panel title="Stop-level crowd risk and bus availability" note="Risk thresholds are configurable operational assumptions, not universal safety limits.">
                {f && <StopTable predict={predict.data} plan={plan.data} targetStep={step} stopId={f.stopId} risk={f.risk} onSelect={(id) => setF({ ...f, stopId: id })} />}
              </Panel>
              <Panel title="What-if results" note="Before (baseline) versus after (scenario)">
                {sim.loading ? <Loading label="Re-running prediction and allocation…" /> : sim.error ? <ErrorBox message={sim.error} /> : sim.data ? <SimulationView sim={sim.data} /> :
                  <Empty>Adjust the what-if controls on the left and choose “Run simulation” to compare against the baseline.</Empty>}
              </Panel>
              <details className="foot"><summary>Data provenance and limitations</summary>
                <ul>{predict.data.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
                {metrics.data && <p>Model: {metrics.data.model.selected}, trained {metrics.data.model.trained_at_utc}. Test one-step MAE {metrics.data.model.test_one_step.mae.toFixed(2)}, RMSE {metrics.data.model.test_one_step.rmse.toFixed(2)}.</p>}
              </details>
            </>
          )}
        </div>
        <div className="rail-col rail-col-right">
        <aside className="rail rail-right">
          <Panel title="Assistant" note="Explains backend results" id="assistant">
            <Assistant onAsk={ask} history={chat} busy={busy} error={chatErr} includeScenario={useScenario} setIncludeScenario={setUseScenario} scenarioActive={!isBaseline(scenario)} />
          </Panel>
        </aside>
        </div>
      </main>
    </div>
  );
}
