import { num } from "../format";

export interface Series { key: string; label: string; color: string; dash?: string; values: (number | null)[] }
interface Props {
  labels: string[]; series: Series[]; band?: { low: number[]; high: number[]; label: string };
  dots?: Series; unit?: string; title: string;
}

const W = 640, H = 250, PL = 46, PR = 14, PT = 12, PB = 30;

export default function LineChart({ labels, series, band, dots, unit = "passengers per 15 min", title }: Props) {
  const all = [...series.flatMap((s) => s.values), ...(band ? band.high : []), ...(dots ? dots.values : [])].filter((v): v is number => v !== null);
  const raw = Math.max(10, ...all) * 1.05;
  const mag = Math.pow(10, Math.floor(Math.log10(raw / 4)));
  const stepY = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v * 4 >= raw) ?? mag * 10;
  const ymax = stepY * 4;
  const x = (i: number) => PL + (labels.length <= 1 ? 0 : (i * (W - PL - PR)) / (labels.length - 1));
  const y = (v: number) => PT + (1 - v / ymax) * (H - PT - PB);
  const ticks = [0, 1, 2, 3, 4].map((i) => i * stepY);
  const path = (vals: (number | null)[]) =>
    vals.map((v, i) => (v === null ? null : `${i === 0 || vals[i - 1] === null ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(" ");
  const every = Math.max(1, Math.ceil(labels.length / 8));
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} preserveAspectRatio="xMidYMid meet">
        <title>{title}</title>
        {ticks.map((t) => (
          <g key={t}><line x1={PL} x2={W - PR} y1={y(t)} y2={y(t)} className="gridline" /><text x={PL - 6} y={y(t) + 4} className="axis" textAnchor="end">{num(t)}</text></g>
        ))}
        {labels.map((l, i) => i % every === 0 && <text key={l + i} x={x(i)} y={H - 10} className="axis" textAnchor="middle">{l}</text>)}
        {band && <path className="band" d={`${band.high.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ")} ${band.low.map((_, i) => `L${x(band.low.length - 1 - i)},${y(band.low[band.low.length - 1 - i])}`).join(" ")} Z`} />}
        {series.map((s) => <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2.4} strokeDasharray={s.dash} strokeLinejoin="round" />)}
        {dots?.values.map((v, i) => v !== null && <circle key={i} cx={x(i)} cy={y(v)} r={3.6} fill="#fff" stroke={dots.color} strokeWidth={2} />)}
      </svg>
      <figcaption className="legend">
        {series.map((s) => <span key={s.key}><i className="swatch" style={{ borderColor: s.color, borderStyle: s.dash ? "dashed" : "solid" }} />{s.label}</span>)}
        {band && <span><i className="swatch swatch-band" />{band.label}</span>}
        {dots && <span><i className="dot" style={{ borderColor: dots.color }} />{dots.label}</span>}
        <span className="unit">{unit}</span>
      </figcaption>
    </figure>
  );
}
