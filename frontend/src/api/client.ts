import type {
  AnnouncementResponse, AssistantResponse, BriefingResponse, ChaosResponse, FestivalsResponse, ForecastParams, Health, MetricsResponse, OptimiseResponse, PredictResponse,
  Scenario, SimulateResponse, StopsResponse,
} from "../types";

/** Central API client.
 *  By default the browser talks to the SAME origin ("/api/...") and the Vite dev/preview server forwards those calls to the FastAPI
 *  backend on 127.0.0.1:8000 (see vite.config.ts). That avoids CORS and the Windows "localhost -> ::1 (IPv6)" problem completely.
 *  Set VITE_API_BASE_URL (frontend/.env.local) only if the backend runs somewhere else; "localhost" is rewritten to 127.0.0.1. */
const RAW_BASE: string = (import.meta.env.VITE_API_BASE_URL || "").trim();
export const API_BASE_URL: string = RAW_BASE
  ? RAW_BASE.replace(/\/$/, "").replace("//localhost", "//127.0.0.1")
  : import.meta.env.MODE === "test" ? "http://127.0.0.1:8000" : "";  // vitest/jsdom has no dev-server proxy, so tests go direct
/** Human-readable backend location for messages. */
export const API_LABEL: string = API_BASE_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
    this.name = "ApiError";
  }
}

interface Opts { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal; timeoutMs?: number }

async function request<T>(path: string, { method = "GET", body, signal, timeoutMs = 30_000 }: Opts = {}): Promise<T> {
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, timeoutMs);
  const onAbort = () => ctrl.abort();
  signal?.addEventListener("abort", onAbort);
  try {
    const res = await fetch(API_BASE_URL + path, {
      method, signal: ctrl.signal,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`; let code: string | undefined;
      try { const j = await res.json(); detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); code = j.code; } catch { /* non-JSON error body */ }
      throw new ApiError(res.status, detail, code);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (signal?.aborted) throw e;  // caller cancelled: let the hook ignore it
    if (timedOut) throw new ApiError(0, `The API did not answer within ${timeoutMs / 1000}s.`, "timeout");
    throw new ApiError(0, `Cannot reach the API at ${API_LABEL}. Start the backend (see README).`, "network");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/api/health", { signal, timeoutMs: 6000 }),
  festivals: (signal?: AbortSignal) => request<FestivalsResponse>("/api/festivals", { signal }),
  stops: (signal?: AbortSignal) => request<StopsResponse>("/api/stops", { signal }),
  metrics: (signal?: AbortSignal) => request<MetricsResponse>("/api/metrics", { signal }),
  predict: (p: ForecastParams, signal?: AbortSignal) => request<PredictResponse>("/api/predict", { method: "POST", body: p, signal }),
  optimise: (p: ForecastParams & { target_step: number }, signal?: AbortSignal) =>
    request<OptimiseResponse>("/api/optimise", { method: "POST", body: p, signal }),
  simulate: (p: ForecastParams & { target_step: number; scenario: Scenario }, signal?: AbortSignal) =>
    request<SimulateResponse>("/api/simulate", { method: "POST", body: p, signal, timeoutMs: 60_000 }),
  assistant: (body: unknown, signal?: AbortSignal) =>
    request<AssistantResponse>("/api/assistant", { method: "POST", body, signal, timeoutMs: 60_000 }),
  briefing: (body: unknown, signal?: AbortSignal) =>
    request<BriefingResponse>("/api/briefing", { method: "POST", body, signal, timeoutMs: 60_000 }),
  chaos: (body: unknown, signal?: AbortSignal) =>
    request<ChaosResponse>("/api/chaos", { method: "POST", body, signal, timeoutMs: 120_000 }),
  announcements: (body: unknown, signal?: AbortSignal) =>
    request<AnnouncementResponse>("/api/announcements", { method: "POST", body, signal, timeoutMs: 60_000 }),
};

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";
