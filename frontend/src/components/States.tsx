import type { ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="state state-loading" role="status" aria-live="polite"><span className="spinner" aria-hidden />{label}</div>;
}
export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>Could not load this section.</strong>
      <span>{message}</span>
      {onRetry && <button className="btn btn-quiet" onClick={onRetry}>Try again</button>}
    </div>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}
export function Panel({ title, note, children, actions, id }: { title: string; note?: ReactNode; children: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <section className="panel" aria-labelledby={id ? `${id}-h` : undefined} id={id}>
      <header className="panel-head">
        <div><h2 id={id ? `${id}-h` : undefined}>{title}</h2>{note && <p className="panel-note">{note}</p>}</div>
        {actions}
      </header>
      {children}
    </section>
  );
}
export function Tag({ kind, children }: { kind: "input" | "model" | "sim" | "advisory"; children: ReactNode }) {
  return <span className={`tag tag-${kind}`}>{children}</span>;
}
