/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Where the FastAPI backend listens. Override with BACKEND_URL=http://host:port when starting vite if needed.
const BACKEND: string = (globalThis as any).process?.env?.BACKEND_URL || "http://127.0.0.1:8000";

// Forward same-origin /api/* calls to the backend (no CORS, no localhost/IPv6 mix-ups). If the backend is not running, answer with
// a clear JSON error (code "network") instead of an empty 500, so the UI can show "start the backend" and keep retrying.
const proxy = {
  "/api": {
    target: BACKEND,
    changeOrigin: true,
    configure: (p: any) => {
      p.on("error", (_err: unknown, _req: unknown, res: any) => {
        if (res && typeof res.writeHead === "function" && !res.headersSent) {
          res.writeHead(503, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ detail: `Cannot reach the API at ${BACKEND}. Start the backend (see README).`, code: "network" }));
        }
      });
    },
  },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { proxy },
  test: { environment: "jsdom", globals: true, testTimeout: 30000 },
});
