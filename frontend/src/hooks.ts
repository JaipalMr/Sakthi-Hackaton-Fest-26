import { useEffect, useState } from "react";
import { isAbort } from "./api/client";

export interface Remote<T> { data: T | null; error: string | null; loading: boolean }

/** Runs `fn` whenever deps change; cancels stale requests; keeps previous data visible while reloading. */
export function useRemote<T>(fn: ((signal: AbortSignal) => Promise<T>) | null, deps: unknown[]): Remote<T> {
  const [state, setState] = useState<Remote<T>>({ data: null, error: null, loading: fn !== null });
  useEffect(() => {
    if (!fn) { setState({ data: null, error: null, loading: false }); return; }
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    fn(ctrl.signal)
      .then((data) => { if (!ctrl.signal.aborted) setState({ data, error: null, loading: false }); })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted || isAbort(e)) return;
        setState({ data: null, error: e instanceof Error ? e.message : String(e), loading: false });
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}
