"""FastAPI application. Run from the repository root:  uvicorn backend.app.main:app --reload --port 8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app import config
from backend.app.assistant import briefing as briefing_service
from backend.app.assistant import extras as extras_service
from backend.app.assistant import service as assistant_service
from backend.app.data_store import DataStore
from backend.app.errors import ServiceError
from backend.app.model_service import ModelService
from backend.app.pipeline import Services, optimise_plan, predict, simulate
from backend.app.schemas import (AssistantRequest, AssistantResponse, AnnouncementRequest, AnnouncementResponse, BriefingRequest, BriefingResponse, ChaosRequest, ChaosResponse, HealthResponse, OptimiseRequest, OptimiseResponse,
                                 PredictRequest, PredictResponse, SimulateRequest, SimulateResponse)
from ml import network as net

log = logging.getLogger("api")


def create_app(settings: config.Settings | None = None, data_path=None, model_path=None) -> FastAPI:
    config.load_dotenv()
    settings = settings or config.get_settings()
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        problems: list[str] = []
        store = None
        try:
            store = DataStore(data_path or config.DATA_PATH)
        except FileNotFoundError:
            problems.append("Dataset missing - run: python -m ml.generate_dataset")
        model = ModelService(model_path or config.MODEL_PATH, auto_train=model_path is None)
        if model.load_error:
            problems.append(model.load_error)
        state.update(store=store, model=model, problems=problems,
                     svc=Services(store, model, settings) if store else None)
        yield

    app = FastAPI(title="Festival Crowd & Transport Demand API", version=config.APP_VERSION, lifespan=lifespan,
                  description="PREDICT -> OPTIMISE -> EXPLAIN -> SIMULATE. All data is SYNTHETIC; outputs are advisory.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?", allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Content-Type"], allow_credentials=False)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        msgs = [f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "Invalid request: " + "; ".join(msgs), "code": "validation_error"})

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "Internal server error. See server logs.", "code": "internal_error"})

    def svc() -> Services:
        if state.get("svc") is None:
            raise ServiceError(503, "; ".join(state.get("problems") or ["Service not ready"]), "not_ready")
        return state["svc"]

    @app.get("/api/health", response_model=HealthResponse)
    def health():
        store, model = state.get("store"), state.get("model")
        problems = list(state.get("problems", []))
        return HealthResponse(
            status="ok" if not problems else "degraded", version=config.APP_VERSION,
            time_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            dataset_loaded=store is not None, dataset_rows=store.rows if store else 0,
            model_loaded=bool(model and model.loaded), llm_mode="live" if settings.llm_live else "demo",
            llm_provider=settings.llm_provider if settings.llm_live else None,
            llm_model=settings.llm_model if settings.llm_live else None, details=problems)

    @app.get("/api/festivals")
    def festivals():
        s = svc()
        out = s.store.festivals()
        for f in out:
            f["split_role"] = s.model.role_of(f["festival_id"])
        return dict(festivals=out, slot_minutes=net.SLOT_MIN, data_is_synthetic=True)

    @app.get("/api/stops")
    def stops():
        s = svc()
        tm = [dict(origin=a, destination=b, minutes=m) for (a, b), m in net.travel_time_matrix().items()]
        return dict(stops=s.store.stops(), travel_minutes=tm, data_is_synthetic=True,
                    note="Illustrative fictional network; coordinates are placeholders, not a real transit system.")

    @app.get("/api/metrics")
    def metrics():
        s = svc()
        s.model.require()
        m = s.model.metadata
        return dict(
            model=dict(selected=m["selected_model"], trained_at_utc=m["trained_at_utc"], sklearn_version=m["sklearn_version"],
                       features=m["features"], split=m["split"], baselines=m["baselines"], candidates=m["candidates"],
                       test_one_step=m["test_one_step"], horizon_metrics=m["horizon_metrics"], interval_method=m["interval_method"],
                       final_fit=m["final_fit"]),
            dataset=dict(rows=s.store.rows, festivals=len(s.store.festival_ids()), stops=len(net.STOPS), synthetic=True,
                         note="Synthetic demonstration data; metrics do not describe real-world accuracy."),
            limitations=m["limitations"])

    @app.post("/api/predict", response_model=PredictResponse)
    def post_predict(req: PredictRequest):
        return predict(svc(), req, req.scenario)

    @app.post("/api/optimise", response_model=OptimiseResponse)
    def post_optimise(req: OptimiseRequest):
        return optimise_plan(svc(), req)

    @app.post("/api/simulate", response_model=SimulateResponse)
    def post_simulate(req: SimulateRequest):
        return simulate(svc(), req)

    @app.post("/api/assistant", response_model=AssistantResponse)
    def post_assistant(req: AssistantRequest):
        return assistant_service.answer(svc(), req)

    @app.post("/api/briefing", response_model=BriefingResponse)
    def post_briefing(req: BriefingRequest):
        return briefing_service.build(svc(), req)

    @app.post("/api/chaos", response_model=ChaosResponse)
    def post_chaos(req: ChaosRequest):
        return extras_service.chaos_report(svc(), req)

    @app.post("/api/announcements", response_model=AnnouncementResponse)
    def post_announcements(req: AnnouncementRequest):
        return extras_service.announcements(svc(), req)

    return app


app = create_app()
