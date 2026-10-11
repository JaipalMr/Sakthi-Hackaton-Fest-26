# Festival Crowd & Transport Demand - full-stack GenAI prototype

**PREDICT -> OPTIMISE -> EXPLAIN -> SIMULATE.** React + TypeScript (Vite) dashboard, FastAPI backend, scikit-learn
demand model, deterministic bus-allocation engine, tool-calling GenAI assistant and what-if simulator.

> **All data is synthetic** (15,000 generated rows). Model accuracy, risk levels and simulation results describe synthetic
> data only. Bus recommendations are **advisory and require human approval** before any real dispatch.

## Quick start (easiest)
- **Windows:** double-click `run_windows.bat` (needs Python 3.10+ and Node 18+). It installs everything on the first run, starts the backend and frontend and opens http://127.0.0.1:5173.
- **macOS/Linux:** `./run.sh`

The first backend start may take about a minute: if the saved model does not match your scikit-learn version it is retrained automatically (port 8000 only opens once that is done).

**"API offline / Cannot reach the backend"** means the Python backend is not running (the page only shows the UI; all numbers come from the backend).
* Easiest: use `run_windows.bat` / `./run.sh` - they start both. Do not start only `npm run dev`.
* Manual: from the repository root run `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` (use `python -m`, plain `uvicorn` is often not on PATH on Windows) and keep that window open.
* The page re-checks every few seconds and loads the data by itself as soon as the backend answers - no refresh needed.
* The dev server forwards `/api` to `http://127.0.0.1:8000` (see `frontend/vite.config.ts`), so no CORS or `localhost`/IPv6 problems. Only if the backend runs elsewhere set `VITE_API_BASE_URL` in `frontend/.env.local`, or start vite with `BACKEND_URL=http://host:port`. Delete `frontend/.env.local` if you are unsure.

## Special features (hackathon edition)
| Feature | What it does | Where |
|---|---|---|
| **Chaos Lab** | "Chaos engineering for festival transport": fires 19 hypothetical disasters (3 rain levels, schedule overrun/early finish, 3 bus shortages, a compound *perfect storm*, and **every single-stop closure**) through the same forecast + optimiser, judges each on its **worst slot** in the window, and returns a 0-100 **resilience score**, a **weakest-link stop**, ranked scenario bars and hardening tips. The LLM writes a red-team debrief from those facts (template fallback). | `POST /api/chaos`, `backend/app/chaos.py` |
| **Time Machine** | Scrub or autoplay the forecast; the network map re-colours and resizes for every 15-minute slot. Advised moves stay tied to the allocation slot. | `frontend/src/components/TimeMachine.tsx` |
| **Multilingual PA announcements** | Drafts passenger announcements (English, Hindi, Tamil, Spanish) naming the crowded stop, a calmer alternative stop and a wait time - all derived from the forecast. LLM output is validated (no invented numbers, stop name must appear) and falls back per language to reviewed templates. Browser text-to-speech playback. Always labelled as DRAFT needing bilingual human review. | `POST /api/announcements`, `backend/app/assistant/extras.py` |
| **Dispatch Desk** | Human-in-the-loop workflow: approve/reject each advised bus move, keep an audit log (order id, time, dispatcher) and download a dispatch sheet. Local to the browser; no real dispatch. | `frontend/src/components/DispatchDesk.tsx` |
| **Voice** | Ask the assistant by microphone and have briefings / debriefs / announcements read aloud (Web Speech API; Chrome/Edge/Safari; hidden if unsupported). | `frontend/src/speech.ts` |
| **AI shift briefing** | Plain-language summary of the window narrated by the LLM from backend facts. | `POST /api/briefing` |

## Layout
```
frontend/  React+TS+Vite UI (components, SVG charts, network view, central API client src/api/client.ts)
backend/   FastAPI app, Pydantic schemas, model service, optimiser, scenario simulator, assistant (tools, provider adapter, demo mode)
ml/        dataset generator, validator, shared network model, features, training/evaluation, artefacts/
data/      festival_transport_demand.csv (15,000 rows) + README.md (documentation)
tests/     dataset, API, prediction, allocation-constraint and GenAI-fallback tests (pytest)
```

## Prerequisites
Python 3.10+ and Node 18+ (tested with Python 3.12, Node 22).

## One-time setup (repository root)
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # optional; see "LLM" below
python -m ml.generate_dataset      # writes data/festival_transport_demand.csv (exactly 15,000 rows, reproducible)
python -m ml.validate_dataset      # must print VALIDATION PASSED
python -m ml.train                 # trains + compares models, saves ml/artifacts/demand_model.joblib and metrics.json
cd frontend && npm install && cd ..       # no .env.local needed: the dev server proxies /api to the backend
```
(The generated CSV and trained artefact are already included in the delivered zip; re-running is safe and deterministic for the CSV.)

## Start the servers (two terminals)
**Terminal 1 - backend (from repo root):**
```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```
API docs: http://localhost:8000/docs - health: http://localhost:8000/api/health

**Terminal 2 - frontend:**
```bash
cd frontend
npm run dev            # http://127.0.0.1:5173  (forwards /api to the backend on 127.0.0.1:8000)
```
Point the UI at another backend with `VITE_API_BASE_URL` in `frontend/.env.local` (then add the frontend origin to `CORS_ORIGINS` in `.env`).

## Endpoints
`GET /api/health`, `/api/festivals`, `/api/stops`, `/api/metrics`; `POST /api/predict`, `/api/optimise`, `/api/simulate`, `/api/assistant`, `/api/briefing`, `/api/chaos`, `/api/announcements`.
Inputs are validated with Pydantic (422 with a readable message; 404 unknown festival; 503 if model/dataset missing).
Example:
```bash
curl -X POST localhost:8000/api/predict -H 'Content-Type: application/json' \
  -d '{"festival_id":"FEST-2025-05","forecast_origin":"2025-11-16T21:00:00","horizon_steps":8}'
```
`forecast_origin` must be a 15-minute slot present in the dataset (see `/api/festivals`).
The forecast horizon h=1 is the slot starting at the origin; observed data is known up to the previous slot.

## Configure the LLM (backend only)
Two providers are supported; the key is read only by the backend and never reaches the browser.

**Anthropic (Claude)** - in `.env`: `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=<key>`, optional `LLM_MODEL=` (default `claude-sonnet-5-5`).

**Any OpenAI-compatible API** (OpenAI, Groq, Together, or local Ollama / LM Studio) - in `.env`:
```
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini                 # or llama3.1 for Ollama
OPENAI_API_KEY=<key>                  # not needed for local servers
OPENAI_BASE_URL=http://localhost:11434/v1   # optional; empty = api.openai.com
```
Restart the backend. `/api/health` reports `"llm_mode":"live"` and the UI header shows "Assistant: live <provider>".

### What the LLM does
1. **Chat assistant** (`POST /api/assistant`): structured tool calling (`get_stop_data`, `get_demand_forecast`, `get_deployment_recommendations`,
   `run_what_if_simulation`). Arguments are validated (extra fields, ranges, stop ids), an answer given without any tool call is discarded, and
   numbers not found in tool output are flagged as warnings.
2. **AI shift briefing** (`POST /api/briefing`, new): the backend computes the forecast and optimiser results, then the LLM only *narrates* them in
   3-5 sentences. The UI card also shows deterministic top-risk stops and advised moves next to the narrative. Numbers in the narrative are checked
   against the backend facts.

Without a key (or if the LLM call times out or errors) both features fall back to **demo mode**: deterministic rule-based routing/templates over the
*same backend tools*. Every demo text is prefixed `[DEMO MODE - ...]`, the UI shows a "Demo mode"/"Template" badge, and the API returns `mode: "demo"`
plus a `fallback_reason` when a live attempt failed.

## Machine learning (measured on the synthetic data)
Chronological 60/20/20 split by timestamp (boundaries fall between festivals: 3 train, 1 validation, 1 test festival).
Baselines: persistence and stop x phase mean. Candidates: HistGradientBoosting, RandomForest (chosen on validation RMSE), refit on
train+validation, test set used once. Features exclude the target; the only demand-derived input is the previous-slot count.
Multi-step forecasts are recursive. Intervals are empirical 10-90% residual bands per horizon.
Latest run (`ml/artifacts/metrics.json`, one-step, test festival): model MAE 5.36 / RMSE 9.75 vs persistence 8.06 / 17.00
and stop-phase mean 10.26 / 21.74; empirical coverage of the nominal 80% interval 75-78% on test. Error grows with horizon
(MAE 8.6 at 12 steps). **These figures are for synthetic data only.**
Experiment worth following up: a lag-free direct model had better long-horizon RMSE (12.4) but worse short-horizon accuracy.

## Optimiser
`backend/app/optimiser.py` - pure, deterministic Python (no ML/LLM). Greedy one-bus-at-a-time moves toward the stop with the largest
unmet demand. Hard constraints: donors keep >= `OPS_MIN_BUSES_PER_STOP` buses and enough capacity for their own forecast plus
`OPS_RESERVE_MARGIN`; destinations stay within bay capacity; travel time (closed routes infeasible) must fit within lead time minus
`OPS_DISPATCH_BUFFER_MIN`; fleet is conserved; per-slot throughput never exceeds buses x vehicle capacity. Every response carries a
`constraint_audit`. Risk thresholds (`OPS_*`) are operational assumptions, **not** universal crowd-safety limits.

## What-if simulation
Controls: festival end shift (+-60 min), rainfall override, bus availability (30-150%), route closures. The backend rewrites forecast-input
features (schedule, rain -> travel time, closure effects), re-runs prediction and allocation and returns baseline vs scenario, labelled
as simulated assumptions. Warnings appear when a scenario leaves the training range. No spill-over of passengers is modelled on closure.

## Tests and verification
```bash
python -m pytest -q                      # 54 backend tests (dataset, API, prediction, allocation constraints, GenAI fallback)
cd frontend && npm run typecheck && npm run build
npm test                                 # needs the backend running on :8000; renders <App/> against the live API (jsdom)
```
### What was actually verified in the build session
* Dataset: exactly 15,000 data rows, validation passes, regeneration byte-identical (same MD5).
* Model trained and saved; metrics above are from that run.
* FastAPI started; `/api/health`, `/api/predict`, `/api/optimise`, `/api/simulate`, `/api/assistant` exercised with curl and pytest; CORS preflight verified.
* Backend pytest: 54 passed (includes briefing, OpenAI-compatible adapter, Chaos Lab and announcement tests). Frontend typecheck, production build and 6 live-backend integration tests passed (briefing, announcements + dispatch approval, Chaos Lab, time machine). Headless Chromium screenshot checked after the UI redesign (1440 px and 390 px, no horizontal overflow).
* Real headless Chromium (Playwright) loaded the dev server, fetched real API responses (CORS OK), applied a map filter, ran a what-if
  simulation and asked the assistant (demo mode). Layout checked at 1440 px and 390 px (no horizontal overflow).
### Not verified / limitations
* Chaos Lab takes ~9 s on first run per window (19 scenarios x ~5 slots; cached afterwards). Its score is a transparent heuristic on synthetic data, not a safety certification; the model's response to rain is not strictly monotonic (e.g. 5 mm/h can score worse than 12 mm/h).
* Hindi/Tamil/Spanish announcement templates were written by an AI and not reviewed by native speakers; speech playback depends on voices installed in the browser/OS.
* Voice input needs a browser with SpeechRecognition (Chrome/Edge) and microphone permission; not exercised in the headless test.
* **Live LLM paths (Anthropic and OpenAI-compatible) were NOT tested against a real provider** (no API key in the build environment). They are covered only by tests with scripted fake providers and by a message-translation unit test for the OpenAI adapter.
* Google Fonts could not load in the sandbox (system fallbacks used).
* Weather/fleet/route inputs for forecast slots are the dataset's values treated as perfect forecasts; only 5 synthetic festivals exist.
* Backlog/crowding estimates and optimiser impact figures are model estimates, not measurements.
* The optimiser is a greedy heuristic, not a proven optimum; it plans one slot at a time.
