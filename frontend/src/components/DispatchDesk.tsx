import { useState } from "react";
import type { OptimiseResponse } from "../types";
import { Empty } from "./States";
import { hhmm, num } from "../format";

export interface Order { id: string; key: string; at: string; slot: string; festival: string; buses: number; from: string; to: string; minutes: number; decision: "approved" | "rejected"; by: string }
export const orderKey = (plan: OptimiseResponse, r: OptimiseResponse["recommendations"][number]) => `${plan.target_timestamp}|${plan.target_step}|${r.origin_stop_name}|${r.destination_stop_name}|${r.buses}`;

interface Props { plan: OptimiseResponse | null; festival: string; orders: Order[]; onDecide: (o: Omit<Order, "id" | "at">) => void }

/** DISPATCH DESK: human-in-the-loop approval workflow with an audit trail and a printable dispatch sheet. */
export default function DispatchDesk({ plan, festival, orders, onDecide }: Props) {
  const [by, setBy] = useState("");
  if (!plan) return <Empty>Waiting for the optimiser…</Empty>;
  const done = new Set(orders.map((o) => o.key));
  const pending = plan.recommendations.filter((r) => !done.has(orderKey(plan, r)));
  const decide = (r: OptimiseResponse["recommendations"][number], decision: Order["decision"]) =>
    onDecide({ key: orderKey(plan, r), slot: hhmm(plan.target_timestamp), festival, buses: r.buses, from: r.origin_stop_name, to: r.destination_stop_name, minutes: r.travel_time_min, decision, by: by.trim() || "Dispatcher" });
  const approved = orders.filter((o) => o.decision === "approved");
  const download = () => {
    const lines = ["FESTIVAL TRANSPORT - DISPATCH SHEET", `Generated: ${new Date().toLocaleString()}`, "NOTE: prototype on SYNTHETIC data; approvals are recorded locally only and trigger no real dispatch.", ""];
    approved.forEach((o) => lines.push(`${o.id}  ${o.at}  slot ${o.slot}  ${o.buses} bus(es)  ${o.from} -> ${o.to}  (${Math.round(o.minutes)} min)  approved by ${o.by}`));
    const url = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/plain" }));
    const a = document.createElement("a"); a.href = url; a.download = "dispatch-sheet.txt"; a.click(); URL.revokeObjectURL(url);
  };
  return (
    <div className="desk">
      <div className="desk-bar">
        <label className="desk-name">Your name<input value={by} onChange={(e) => setBy(e.target.value)} placeholder="Dispatcher" aria-label="Dispatcher name" maxLength={40} /></label>
        <span className="desk-count">{pending.length} pending · {approved.length} approved</span>
        <button className="btn btn-quiet" onClick={download} disabled={!approved.length}>⬇ Dispatch sheet</button>
      </div>
      {pending.length === 0 ? <Empty>{plan.recommendations.length ? "All moves for this slot have been decided." : "No bus moves to approve for this slot."}</Empty> : (
        <ul className="desk-list">
          {pending.map((r) => (
            <li key={orderKey(plan, r)}>
              <span><b>{r.buses}</b> bus{r.buses > 1 ? "es" : ""} · {r.origin_stop_name} <i aria-hidden>→</i> {r.destination_stop_name}<small>{num(r.travel_time_min)} min · slot {hhmm(plan.target_timestamp)}</small></span>
              <span className="desk-btns"><button className="btn btn-ok" onClick={() => decide(r, "approved")}>Approve</button><button className="btn btn-quiet" onClick={() => decide(r, "rejected")}>Reject</button></span>
            </li>
          ))}
        </ul>
      )}
      {orders.length > 0 && (
        <details open><summary>Audit log ({orders.length})</summary>
          <ol className="audit">{[...orders].reverse().map((o) => <li key={o.id} className={`audit-${o.decision}`}><code>{o.id}</code> {o.at} · {o.buses} bus{o.buses > 1 ? "es" : ""} {o.from} → {o.to} · <b>{o.decision}</b> by {o.by}</li>)}</ol>
        </details>
      )}
      <p className="hint">Approvals are logged in this browser only. Nothing is sent to real fleet systems.</p>
    </div>
  );
}
