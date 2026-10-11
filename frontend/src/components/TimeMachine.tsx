import { useEffect } from "react";
import type { PredictResponse } from "../types";
import { hhmm, num } from "../format";

interface Props { predict: PredictResponse; viewStep: number; allocStep: number; playing: boolean; setPlaying: (b: boolean) => void; setViewStep: (n: number) => void }

/** TIME MACHINE: scrub or autoplay the forecast; the map below re-colours itself for every 15-minute slot. */
export default function TimeMachine({ predict, viewStep, allocStep, playing, setPlaying, setViewStep }: Props) {
  const n = predict.horizon_steps_returned;
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setViewStep(viewStep >= n ? 1 : viewStep + 1), 1100);
    return () => clearInterval(id);
  }, [playing, viewStep, n, setViewStep]);
  const t = predict.totals_by_step, cur = t[viewStep - 1];
  const high = predict.forecasts.filter((f) => f.steps[viewStep - 1]?.risk_level === "high").length;
  const max = Math.max(...t.map((s) => s.predicted_demand), 1);
  return (
    <div className="tm">
      <button className="btn btn-primary tm-play" onClick={() => setPlaying(!playing)} aria-label={playing ? "Pause playback" : "Play forecast"}>{playing ? "❚❚" : "▶"}</button>
      <div className="tm-main">
        <div className="tm-bars" aria-hidden>
          {t.map((s, i) => <button key={s.step} tabIndex={-1} className={`tm-bar ${i + 1 === viewStep ? "on" : ""} ${i + 1 === allocStep ? "alloc" : ""}`} style={{ height: `${12 + (s.predicted_demand / max) * 34}px` }} onClick={() => { setPlaying(false); setViewStep(i + 1); }} />)}
        </div>
        <input type="range" min={1} max={n} value={viewStep} aria-label="Time machine slot" onChange={(e) => { setPlaying(false); setViewStep(Number(e.target.value)); }} />
      </div>
      <div className="tm-read"><b>{hhmm(cur.timestamp)}</b><span>{num(cur.predicted_demand)} passengers · {high} high-risk stop{high === 1 ? "" : "s"}</span></div>
    </div>
  );
}
