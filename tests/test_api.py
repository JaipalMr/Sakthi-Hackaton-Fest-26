from tests.conftest import FEST, ORIGIN


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok" and d["dataset_rows"] == 15000 and d["model_loaded"] is True and d["llm_mode"] == "demo"


def test_stops_and_festivals(client):
    s = client.get("/api/stops").json()
    assert len(s["stops"]) == 10 and len(s["travel_minutes"]) == 90
    f = client.get("/api/festivals").json()
    assert len(f["festivals"]) == 5
    roles = {x["festival_id"]: x["split_role"] for x in f["festivals"]}
    assert roles[FEST] == "test" and roles["FEST-2025-01"] == "train"
    assert all(len(d["slots"]) == 50 for x in f["festivals"] for d in x["days"])


def test_metrics_report_measured_values(client):
    m = client.get("/api/metrics").json()
    assert m["dataset"]["rows"] == 15000 and m["dataset"]["synthetic"] is True
    assert m["model"]["test_one_step"]["mae"] > 0 and len(m["model"]["horizon_metrics"]) == 12
    assert m["limitations"]


def test_predict_ok(client, ctx_body):
    r = client.post("/api/predict", json={**ctx_body, "stop_ids": ["S01", "S04"]})
    assert r.status_code == 200
    d = r.json()
    assert [f["stop_id"] for f in d["forecasts"]] == ["S01", "S04"]
    assert d["provenance"]["data_is_synthetic"] is True and d["model"]["festival_split_role"] == "test"
    assert d["limitations"]


def test_predict_validation_errors(client, ctx_body):
    assert client.post("/api/predict", json={**ctx_body, "festival_id": "NOPE"}).status_code == 404
    assert client.post("/api/predict", json={**ctx_body, "forecast_origin": "2025-11-16T21:07:00"}).status_code == 422
    assert client.post("/api/predict", json={**ctx_body, "horizon_steps": 0}).status_code == 422
    assert client.post("/api/predict", json={**ctx_body, "stop_ids": ["S99"]}).status_code == 422
    assert client.post("/api/predict", json={**ctx_body, "forecast_origin": "2025-11-16T21:00:00+05:30"}).status_code == 422
    assert client.post("/api/predict", json={**ctx_body, "bogus": 1}).status_code == 422
    assert client.post("/api/predict", json={}).status_code == 422
    assert client.post("/api/predict", content="not json", headers={"Content-Type": "application/json"}).status_code == 422


def test_optimise_ok_and_validation(client, ctx_body):
    r = client.post("/api/optimise", json={**ctx_body, "target_step": 3})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "advisory" and d["requires_human_approval"] is True
    assert all(c["satisfied"] for c in d["constraint_audit"])
    assert client.post("/api/optimise", json={**ctx_body, "target_step": 13}).status_code == 422
    assert client.post("/api/optimise", json={**ctx_body, "target_step": 5, "forecast_origin": "2025-11-16T23:45:00"}).status_code == 422


def test_simulate_ok_and_empty_scenario_rejected(client, ctx_body):
    sc = {"rainfall_mm_per_hr": 12, "festival_end_shift_min": 30, "bus_availability_factor": 0.8, "closed_stop_ids": ["S06"]}
    r = client.post("/api/simulate", json={**ctx_body, "target_step": 3, "scenario": sc})
    assert r.status_code == 200
    d = r.json()
    assert d["scenario_totals"][0]["actual_demand_synthetic"] is None and d["baseline_totals"][0]["actual_demand_synthetic"] is not None
    assert "not verified" in d["labels"]["warning"]
    assert len(d["stop_deltas"]) == 10
    assert client.post("/api/simulate", json={**ctx_body, "scenario": {}}).status_code == 422
    assert client.post("/api/simulate", json={**ctx_body, "scenario": {"rainfall_mm_per_hr": 99}}).status_code == 422
    assert client.post("/api/simulate", json={**ctx_body, "scenario": {"closed_stop_ids": ["S77"]}}).status_code == 422


def test_assistant_endpoint_demo(client, ctx_body):
    body = {"message": "Where should buses move?", "context": {**ctx_body, "target_step": 3}}
    r = client.post("/api/assistant", json=body)
    assert r.status_code == 200 and r.json()["mode"] == "demo"
    assert client.post("/api/assistant", json={**body, "message": ""}).status_code == 422


def test_cors_preflight_for_local_frontend(client):
    r = client.options("/api/predict", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                                "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r = client.options("/api/predict", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_missing_model_gives_503(tmp_path, settings):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    with TestClient(create_app(settings, model_path=tmp_path / "nope.joblib")) as c:
        h = c.get("/api/health").json()
        assert h["status"] == "degraded" and h["model_loaded"] is False
        r = c.post("/api/predict", json={"festival_id": FEST, "forecast_origin": ORIGIN})
        assert r.status_code == 503 and "ml.train" in r.json()["detail"]
