import type { Festival, Stop } from "../types";
import { cleanName, hhmm } from "../format";

export interface FilterState { festivalId: string; dayIdx: number; slotIdx: number; horizon: number; targetStep: number; stopId: string | null; risk: "all" | "elevated" | "high" }

interface Props { festivals: Festival[]; stops: Stop[]; value: FilterState; onChange: (v: FilterState) => void; maxStep: number }

export default function Filters({ festivals, stops, value, onChange, maxStep }: Props) {
  const fest = festivals.find((f) => f.festival_id === value.festivalId) ?? festivals[0];
  const day = fest.days[Math.min(value.dayIdx, fest.days.length - 1)];
  const set = (p: Partial<FilterState>) => onChange({ ...value, ...p });
  const roleText: Record<string, string> = { train: "training data (in-sample)", validation: "validation data (in-sample)", test: "held-out test data", unknown: "unknown" };
  return (
    <div className="controls">
      <label>Festival
        <select value={fest.festival_id} onChange={(e) => set({ festivalId: e.target.value, dayIdx: 0, slotIdx: 20 })}>
          {festivals.map((f) => <option key={f.festival_id} value={f.festival_id}>{cleanName(f.name)}</option>)}
        </select>
      </label>
      <p className="hint">Model used this festival as <b>{roleText[fest.split_role] ?? fest.split_role}</b>.</p>
      <label>Festival day
        <select value={value.dayIdx} onChange={(e) => set({ dayIdx: Number(e.target.value) })}>
          {fest.days.map((d, i) => <option key={d.date} value={i}>Day {d.festival_day} · {d.date} (ends {d.scheduled_end})</option>)}
        </select>
      </label>
      <label>Forecast from <output>{hhmm(day.slots[Math.min(value.slotIdx, day.slots.length - 1)])}</output>
        <input type="range" min={0} max={day.slots.length - 1} value={Math.min(value.slotIdx, day.slots.length - 1)}
               onChange={(e) => set({ slotIdx: Number(e.target.value) })} aria-label="Forecast origin time" />
      </label>
      <div className="row2">
        <label>Horizon
          <select value={value.horizon} onChange={(e) => { const h = Number(e.target.value); set({ horizon: h, targetStep: Math.min(value.targetStep, h) }); }}>
            {[4, 6, 8, 12].map((h) => <option key={h} value={h}>{h} slots · {h * 15}m</option>)}
          </select>
        </label>
        <label>Allocate for slot
          <select value={Math.min(value.targetStep, maxStep)} onChange={(e) => set({ targetStep: Number(e.target.value) })}>
            {Array.from({ length: maxStep }, (_, i) => i + 1).map((s) => <option key={s} value={s}>+{(s - 1) * 15} min</option>)}
          </select>
        </label>
      </div>
      <label>Stop
        <select value={value.stopId ?? ""} onChange={(e) => set({ stopId: e.target.value || null })}>
          <option value="">All stops</option>
          {stops.map((s) => <option key={s.stop_id} value={s.stop_id}>{s.stop_id} · {s.stop_name}</option>)}
        </select>
      </label>
      <fieldset className="seg"><legend>Show risk</legend>
        {(["all", "elevated", "high"] as const).map((r) => (
          <label key={r} className={value.risk === r ? "on" : ""}><input type="radio" name="risk" checked={value.risk === r} onChange={() => set({ risk: r })} />{r === "all" ? "All" : r === "elevated" ? "Elevated +" : "High only"}</label>
        ))}
      </fieldset>
    </div>
  );
}
