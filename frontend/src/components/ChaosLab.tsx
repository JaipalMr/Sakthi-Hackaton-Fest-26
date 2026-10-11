import type { ChaosResponse } from "../types";
import { Empty, Loading, Tag } from "./States";
import { num } from "../format";
import { canSpeak, speak } from "../speech";

const GRADE_COLOR: Record<string, string> = { A: "#10B981", B: "#84CC16", C: "#F59E0B", D: "#F97316", F: "#EF4444" };
const CAT_ICON: Record<string, string> = { weather: "☔", schedule: "⏱", fleet: "🚌", closure: "⛔", compound: "🌪" };

function Gauge({ score, grade }: { score: number; grade: string }) {
  const R = 54, C = 2 * Math.PI * R, color = GRADE_COLOR[grade] ?? "#64748B";
  return (
    <svg viewBox="0 0 140 140" className="gauge" role="img" aria-label={`Resilience score ${score} out of 100, grade ${grade}`}>
      <circle cx="70" cy="70" r={R} className="gauge-track" />
      <circle cx="70" cy="70" r={R} className="gauge-fill" stroke={color} strokeDasharray={`${(score / 100) * C} ${C}`} transform="rotate(-90 70 70)" />
      <text x="70" y="68" textAnchor="middle" className="gauge-score">{score}</text>
      <text x="70" y="90" textAnchor="middle" className="gauge-grade" fill={color}>Grade {grade}</text>
    </svg>
  );
}

interface Props { data: ChaosResponse | null; loading: boolean; error: string | null; onRun: () => void }

/** CHAOS LAB: automated resilience stress-test with an AI red-team debrief. */
export default function ChaosLab({ data, loading, error, onRun }: Props) {
  const sorted = data ? [...data.results].sort((a, b) => b.harm - a.harm) : [];
  return (
    <div className="chaos">
      <div className="briefing-bar">
        <p className="briefing-lead">Fires 19 hypothetical disasters - storms, strikes, overruns and every single-stop closure - through the forecast and optimiser, then scores how well the advised plan copes.</p>
        <button className="btn btn-danger" onClick={onRun} disabled={loading}><span aria-hidden>⚡</span> {data ? "Re-run stress test" : "Run stress test"}</button>
      </div>
      {loading && <Loading label="Running 19 disaster scenarios across the window… (about 10 s)" />}
      {error && <div className="state state-error" role="alert">{error}</div>}
      {!loading && !data && !error && <Empty>Press “Run stress test” to find the weakest link in this transport plan before the festival does.</Empty>}
      {!loading && data && (
        <>
          <div className="chaos-top">
            <Gauge score={data.score} grade={data.grade} />
            <div className="chaos-debrief">
              <div className="chaos-debrief-head">
                <h3>Red-team debrief</h3>
                {data.mode === "live_llm" ? <Tag kind="model">AI · {data.provider}/{data.model}</Tag> : <Tag kind="sim">Template · not an LLM</Tag>}
                {canSpeak() && <button className="btn btn-quiet" onClick={() => speak(data.narrative)} aria-label="Read debrief aloud">🔊 Read aloud</button>}
              </div>
              <p>{data.narrative}</p>
              {data.fallback_reason && <p className="hint warn">LLM unavailable: {data.fallback_reason}</p>}
              {data.warnings.map((w) => <p key={w} className="hint warn">{w}</p>)}
              <ul className="tips">{data.hardening_tips.map((t) => <li key={t}>{t}</li>)}</ul>
            </div>
          </div>
          <ul className="chaos-list" aria-label="Scenario results, worst first">
            {sorted.map((r) => (
              <li key={r.id} className={`cs-${r.status}`}>
                <span className="cs-label"><span aria-hidden>{CAT_ICON[r.category]}</span> {r.label}</span>
                <span className="cs-bar" aria-hidden><i style={{ width: `${Math.max(2, Math.round(r.harm * 100))}%` }} /></span>
                <span className="cs-num">{r.extra_unserved > 0 ? `+${num(r.extra_unserved)} unserved @ ${r.worst_time}` : "coped"}</span>
                <span className={`cs-badge cs-badge-${r.status}`}>{r.status}</span>
              </li>
            ))}
          </ul>
          <details><summary>How the score works</summary><p className="hint">{data.method} Slots tested: {data.slots_tested.join(", ")}. {data.disclaimer}</p></details>
        </>
      )}
    </div>
  );
}
