import type { OptimiseResponse, Stop, StopForecast, StopsResponse } from "../types";
import { RISK_GLYPH, RISK_LABEL, num } from "../format";

const W = 920, H = 580, PAD = 120;
const COLOR = { low: "#0B7A75", elevated: "#D99A00", high: "#C2362B" } as const;

interface Props {
  stops: StopsResponse; forecasts: StopForecast[]; targetStep: number; plan: OptimiseResponse | null;
  selected: string | null; onSelect: (id: string | null) => void; dim: Set<string>;
}

export default function NetworkMap({ stops, forecasts, targetStep, plan, selected, onSelect, dim }: Props) {
  // Schematic (transit-diagram style) layout: geographic bearing kept, distance from the festival gate compressed
  // so the tightly clustered venue stops stay legible. Not to scale.
  const gate = stops.stops.find((s) => s.stop_id === "S01") ?? stops.stops[0];
  const rel = (s: Stop) => {
    const dx = (s.longitude - gate.longitude) * 111.2 * Math.cos((gate.latitude * Math.PI) / 180), dy = (s.latitude - gate.latitude) * 111.2;
    const r = Math.hypot(dx, dy), k = r === 0 ? 0 : Math.pow(r, 0.72) / r;
    return { x: dx * k, y: dy * k };
  };
  const R = Object.fromEntries(stops.stops.map((s) => [s.stop_id, rel(s)]));
  const xs = Object.values(R).map((v) => v.x), ys = Object.values(R).map((v) => v.y);
  const sc = Math.min((W - 2 * PAD) / (Math.max(...xs) - Math.min(...xs) || 1), (H - 2 * PAD) / (Math.max(...ys) - Math.min(...ys) || 1));
  const ox = (W - sc * (Math.max(...xs) - Math.min(...xs))) / 2 - sc * Math.min(...xs), oy = (H - sc * (Math.max(...ys) - Math.min(...ys))) / 2 + sc * Math.max(...ys);
  const P0 = Object.fromEntries(stops.stops.map((s) => [s.stop_id, { x: ox + R[s.stop_id].x * sc, y: oy - R[s.stop_id].y * sc }]));
  const byId = Object.fromEntries(forecasts.map((f) => [f.stop_id, f]));
  const hub = gate;
  const rad = (id: string) => 9 + Math.sqrt(byId[id]?.steps[targetStep - 1]?.predicted_demand ?? 0) * 1.4;
  const radMax = (id: string) => 9 + Math.sqrt(Math.max(0, ...(byId[id]?.steps.map((x) => x.predicted_demand) ?? [0]))) * 1.4;
  // Relax positions so rings never touch (gate stays put), then place each label in a free spot.
  const ids = stops.stops.map((s) => s.stop_id);
  const P: Record<string, { x: number; y: number }> = Object.fromEntries(ids.map((id) => [id, { ...P0[id] }]));
  for (let it = 0; it < 300; it++) {
    for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
      const a = P[ids[i]], b = P[ids[j]];
      let dx = b.x - a.x, dy = b.y - a.y; const d = Math.hypot(dx, dy) || 0.01;
      const need = radMax(ids[i]) + radMax(ids[j]) + 84;
      if (d < need) {
        dx /= d; dy /= d; const push = (need - d) / 2;
        const fa = ids[i] === "S01" ? 0 : 1, fb = ids[j] === "S01" ? 0 : 1, t = fa + fb || 1;
        a.x -= dx * push * 2 * fa / t; a.y -= dy * push * 2 * fa / t; b.x += dx * push * 2 * fb / t; b.y += dy * push * 2 * fb / t;
      }
    }
    for (const id of ids) { const q = P[id]; q.x = Math.min(W - 70, Math.max(70, q.x)); q.y = Math.min(H - 40, Math.max(40, q.y)); }
  }
  type Box = { x1: number; y1: number; x2: number; y2: number };
  const hit = (a: Box, b: Box) => a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1;
  const taken: Box[] = ids.map((id) => ({ x1: P[id].x - rad(id) - 2, y1: P[id].y - rad(id) - 2, x2: P[id].x + rad(id) + 2, y2: P[id].y + rad(id) + 2 }));
  for (const r of plan?.recommendations ?? []) {
    const a0 = P[r.origin_stop_id], b0 = P[r.destination_stop_id];
    const mx = (a0.x + b0.x) / 2 + (b0.y - a0.y) * 0.16, my = (a0.y + b0.y) / 2 - (b0.x - a0.x) * 0.16;
    for (let k = 1; k < 16; k++) { const t = k / 16, x = (1 - t) * (1 - t) * a0.x + 2 * (1 - t) * t * mx + t * t * b0.x, y = (1 - t) * (1 - t) * a0.y + 2 * (1 - t) * t * my + t * t * b0.y; taken.push({ x1: x - 5, x2: x + 5, y1: y - 5, y2: y + 5 }); }
  }
  const labelFor: Record<string, { x: number; y: number; anchor: "start" | "end" | "middle" }> = {};
  const order = [...stops.stops].sort((a, b) => Math.hypot(P[a.stop_id].x - P.S01.x, P[a.stop_id].y - P.S01.y) - Math.hypot(P[b.stop_id].x - P.S01.x, P[b.stop_id].y - P.S01.y));
  for (const s of order) {
    const p = P[s.stop_id], r = rad(s.stop_id), wd = Math.max(s.stop_name.length * 7, 96), g = 9;
    const right = p.x >= P.S01.x;
    const cands = [
      { x: p.x + (right ? r + g : -r - g), y: p.y + 3, anchor: right ? "start" : "end", bx: right ? p.x + r + g : p.x - r - g - wd },
      { x: p.x + (right ? -r - g : r + g), y: p.y + 3, anchor: right ? "end" : "start", bx: right ? p.x - r - g - wd : p.x + r + g },
      { x: p.x, y: p.y - r - 22, anchor: "middle", bx: p.x - wd / 2 },
      { x: p.x, y: p.y + r + 16, anchor: "middle", bx: p.x - wd / 2 },
    ] as const;
    let pick: (typeof cands)[number] = cands[0];
    for (const c of cands) {
      const vert = c.anchor === "middle";
      const box: Box = { x1: c.bx, x2: c.bx + wd, y1: vert ? (c.y === p.y + r + 16 ? p.y + r + 2 : p.y - r - 36) : p.y - 13, y2: vert ? (c.y === p.y + r + 16 ? p.y + r + 32 : p.y - r - 2) : p.y + 22 };
      if (box.x1 >= 4 && box.x2 <= W - 4 && box.y1 >= 2 && box.y2 <= H - 2 && !taken.some((t) => hit(t, box))) { pick = c; taken.push(box); break; }
    }
    if (pick === cands[0]) { const c = pick; taken.push({ x1: c.bx, x2: c.bx + wd, y1: p.y - 13, y2: p.y + 22 }); }
    labelFor[s.stop_id] = { x: pick.x, y: pick.y, anchor: pick.anchor as "start" | "end" | "middle" };
  }
  return (
    <figure className="map">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Network view: stops sized by predicted demand, coloured by crowd risk, with advised bus moves as arrows">
        <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#14262C" /></marker></defs>
        {hub && stops.stops.filter((s) => s.stop_id !== "S01").map((s) => (
          <line key={"l" + s.stop_id} x1={P.S01.x} y1={P.S01.y} x2={P[s.stop_id].x} y2={P[s.stop_id].y} className="route" />
        ))}
        {plan?.recommendations.map((r) => {
          const a0 = P[r.origin_stop_id], b0 = P[r.destination_stop_id];
          const mx = (a0.x + b0.x) / 2 + (b0.y - a0.y) * 0.16, my = (a0.y + b0.y) / 2 - (b0.x - a0.x) * 0.16;
          const unit = (fx: number, fy: number, tx: number, ty: number) => { const d = Math.hypot(tx - fx, ty - fy) || 1; return { x: (tx - fx) / d, y: (ty - fy) / d }; };
          const ua = unit(a0.x, a0.y, mx, my), ub = unit(mx, my, b0.x, b0.y);
          const ra = rad(r.origin_stop_id) + 3, rb = rad(r.destination_stop_id) + 6;
          const a = { x: a0.x + ua.x * ra, y: a0.y + ua.y * ra }, b = { x: b0.x - ub.x * rb, y: b0.y - ub.y * rb };
          return (
            <g key={r.rank}>
              <path d={`M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}`} className="move" markerEnd="url(#arrow)" />
            </g>
          );
        })}
        {stops.stops.map((s) => {
          const f = byId[s.stop_id]; const step = f?.steps[targetStep - 1];
          const risk = step?.risk_level ?? "low"; const demand = step?.predicted_demand ?? 0;
          const r = rad(s.stop_id); const p = P[s.stop_id];
          const faded = dim.has(s.stop_id) || (selected !== null && selected !== s.stop_id);
          const L = labelFor[s.stop_id];
          const toggle = () => onSelect(selected === s.stop_id ? null : s.stop_id);
          return (
            <g key={s.stop_id} className={`node ${faded ? "faded" : ""}`} tabIndex={0} role="button" aria-pressed={selected === s.stop_id}
               aria-label={`${s.stop_name}: ${num(demand)} predicted passengers, risk ${RISK_LABEL[risk]}`}
               onClick={toggle} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle())}>
              <circle cx={p.x} cy={p.y} r={r} fill={COLOR[risk]} fillOpacity={0.16} stroke={COLOR[risk]} strokeWidth={selected === s.stop_id ? 4 : 2.5} />
              <circle cx={p.x} cy={p.y} r={5} fill="#fff" stroke="#14262C" strokeWidth={1.8} />
              <text x={L.x} y={L.anchor === "middle" ? L.y : p.y + 3} textAnchor={L.anchor} className="stop-label">{s.stop_name}</text>
              <text x={L.x} y={(L.anchor === "middle" ? L.y : p.y + 3) + 14} textAnchor={L.anchor} className="stop-sub">{num(demand)} pax · {RISK_GLYPH[risk]} {RISK_LABEL[risk]}</text>
            </g>
          );
        })}
        {plan?.recommendations.map((r) => {
          const a0 = P[r.origin_stop_id], b0 = P[r.destination_stop_id];
          const mx = (a0.x + b0.x) / 2 + (b0.y - a0.y) * 0.16, my = (a0.y + b0.y) / 2 - (b0.x - a0.x) * 0.16;
          const at = (t: number) => ({ x: (1 - t) * (1 - t) * a0.x + 2 * (1 - t) * t * mx + t * t * b0.x, y: (1 - t) * (1 - t) * a0.y + 2 * (1 - t) * t * my + t * t * b0.y });
          const free = [0.5, 0.4, 0.6, 0.3, 0.7, 0.55, 0.45].map(at).find((q) => !taken.some((b) => hit(b, { x1: q.x - 14, x2: q.x + 14, y1: q.y - 20, y2: q.y + 4 }))) ?? at(0.5);
          const qx = free.x, qy = free.y;
          taken.push({ x1: qx - 14, x2: qx + 14, y1: qy - 20, y2: qy + 4 });
          return <text key={"m" + r.rank} x={qx} y={qy - 6} className="move-label" textAnchor="middle" pointerEvents="none">×{r.buses}</text>;
        })}
      </svg>
      <figcaption className="legend">
        <span>Ring size = predicted demand at target slot</span>
        {(["low", "elevated", "high"] as const).map((k) => <span key={k}><i className="dot" style={{ background: COLOR[k], borderColor: COLOR[k] }} />{RISK_GLYPH[k]} {RISK_LABEL[k]}</span>)}
        <span><i className="arrow-key" />Advised bus move (×buses)</span>
        <span className="unit">Illustrative fictional network</span>
      </figcaption>
    </figure>
  );
}
