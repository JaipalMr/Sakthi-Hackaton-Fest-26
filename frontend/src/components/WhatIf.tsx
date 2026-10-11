import type { Scenario, Stop } from "../types";
import { BASELINE, isBaseline } from "../types";

interface Props { value: Scenario; stops: Stop[]; onChange: (s: Scenario) => void; onRun: () => void; running: boolean }

export default function WhatIf({ value, stops, onChange, onRun, running }: Props) {
  const set = (p: Partial<Scenario>) => onChange({ ...value, ...p });
  const toggle = (id: string) => set({ closed_stop_ids: value.closed_stop_ids.includes(id) ? value.closed_stop_ids.filter((x) => x !== id) : [...value.closed_stop_ids, id] });
  return (
    <div className="controls">
      <p className="hint">Change assumptions, then run. Results are <b>simulated</b>, not observed.</p>
      <label>Festival end time <output>{value.festival_end_shift_min > 0 ? "+" : ""}{value.festival_end_shift_min} min</output>
        <input type="range" min={-60} max={60} step={15} value={value.festival_end_shift_min} onChange={(e) => set({ festival_end_shift_min: Number(e.target.value) })} />
      </label>
      <label className="check"><input type="checkbox" checked={value.rainfall_mm_per_hr !== null} onChange={(e) => set({ rainfall_mm_per_hr: e.target.checked ? 8 : null })} />Override rainfall</label>
      {value.rainfall_mm_per_hr !== null && (
        <label>Rainfall <output>{value.rainfall_mm_per_hr} mm/h</output>
          <input type="range" min={0} max={30} step={1} value={value.rainfall_mm_per_hr} onChange={(e) => set({ rainfall_mm_per_hr: Number(e.target.value) })} />
        </label>
      )}
      <label>Bus availability <output>{Math.round(value.bus_availability_factor * 100)}% of plan</output>
        <input type="range" min={0.3} max={1.5} step={0.1} value={value.bus_availability_factor} onChange={(e) => set({ bus_availability_factor: Math.round(Number(e.target.value) * 10) / 10 })} />
      </label>
      <fieldset className="chips"><legend>Close route at stop</legend>
        {stops.map((s) => (
          <button key={s.stop_id} type="button" className={`chip ${value.closed_stop_ids.includes(s.stop_id) ? "on" : ""}`} aria-pressed={value.closed_stop_ids.includes(s.stop_id)} title={s.stop_name} onClick={() => toggle(s.stop_id)}>{s.stop_id}</button>
        ))}
      </fieldset>
      <div className="row2">
        <button className="btn btn-primary" onClick={onRun} disabled={running || isBaseline(value)} title={isBaseline(value) ? "Change at least one assumption first" : undefined}>{running ? "Simulating…" : "Run simulation"}</button>
        <button className="btn btn-quiet" onClick={() => onChange(BASELINE)} disabled={isBaseline(value)}>Reset</button>
      </div>
    </div>
  );
}
