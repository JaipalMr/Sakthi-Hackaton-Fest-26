import type { RiskLevel } from "./types";
export const hhmm = (iso: string) => iso.slice(11, 16);
export const num = (n: number, d = 0) => n.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
export const pct = (n: number) => `${Math.round(n * 100)}%`;
export const RISK_ORDER: Record<RiskLevel, number> = { low: 0, elevated: 1, high: 2 };
export const RISK_LABEL: Record<RiskLevel, string> = { low: "Low", elevated: "Elevated", high: "High" };
export const RISK_GLYPH: Record<RiskLevel, string> = { low: "●", elevated: "▲", high: "◆" };
export const phaseLabel = (p: string) => p.replace("_", " ");

export const cleanName = (n: string) => n.replace(/\s*\(synthetic\)/i, "");
