import type { BriefingResponse } from "../types";
import { Empty, Loading, Tag } from "./States";
import { canSpeak, speak } from "../speech";
import { RISK_GLYPH, RISK_LABEL, num } from "../format";

interface Props {
  data: BriefingResponse | null; loading: boolean; error: string | null; onGenerate: () => void; liveLabel: string | null;
}

/** AI shift briefing: facts are computed by the backend; the LLM (or a labelled template) only narrates them. */
export default function Briefing({ data, loading, error, onGenerate, liveLabel }: Props) {
  return (
    <div className="briefing">
      <div className="briefing-bar">
        <p className="briefing-lead">
          {liveLabel ? <>Narrated by <b>{liveLabel}</b> from backend forecast and optimiser results.</> : <>No LLM configured - a clearly labelled template summary is used. Add a key in <code>.env</code> for AI narration.</>}
        </p>
        <button className="btn btn-primary btn-glow" onClick={onGenerate} disabled={loading}>
          <span aria-hidden>✦</span> {data ? "Regenerate briefing" : "Generate briefing"}
        </button>
      </div>
      {loading && <Loading label="Gathering forecast and writing the briefing…" />}
      {error && <div className="state state-error" role="alert">{error}</div>}
      {!loading && !data && !error && <Empty>Press “Generate briefing” for a plain-language summary of the current window: what is urgent, which buses to move and how confident to be.</Empty>}
      {!loading && data && (
        <article className="brief-card">
          <header>
            <h3>{data.headline}</h3>
            {data.mode === "live_llm" ? <Tag kind="model">AI · {data.provider}/{data.model}</Tag> : <Tag kind="sim">Template · not an LLM</Tag>}
          </header>
          <p className="brief-text">{data.narrative}</p>
          {canSpeak() && <button className="btn btn-ghost" onClick={() => speak(data.narrative)} aria-label="Read briefing aloud">🔊 Read aloud</button>}
          {data.fallback_reason && <p className="hint warn">LLM unavailable: {data.fallback_reason}</p>}
          {data.warnings.map((w) => <p key={w} className="hint warn">{w}</p>)}
          <div className="brief-cols">
            <div>
              <h4>Highest-risk stops</h4>
              <ul className="brief-risks">
                {data.top_risks.map((r) => (
                  <li key={r.stop_id} className={`br-${r.risk}`}>
                    <span className="br-name">{r.stop_name}</span>
                    <span className="br-meta">peak {num(r.peak_demand)} @ {r.peak_time} vs capacity {num(r.service_capacity)}</span>
                    <span className={`risk risk-${r.risk}`}>{RISK_GLYPH[r.risk]} {RISK_LABEL[r.risk]}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4>Advised bus moves <small>(need approval)</small></h4>
              {data.moves.length === 0 ? <p className="hint">No feasible moves for the target slot.</p> : (
                <ul className="brief-moves">
                  {data.moves.map((m, i) => <li key={i}><b>{m.buses}</b> bus{m.buses > 1 ? "es" : ""}<span>{m.from_stop} <i aria-hidden>→</i> {m.to_stop}</span><em>{num(m.travel_min)} min</em></li>)}
                </ul>
              )}
              <p className="brief-impact">Unserved <b>{num(data.unserved_before)}</b> <i aria-hidden>→</i> <b>{num(data.unserved_after)}</b> (estimate)</p>
            </div>
          </div>
        </article>
      )}
    </div>
  );
}
