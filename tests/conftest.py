import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.config import DATA_PATH, MODEL_PATH, OpsConfig, Settings  # noqa: E402
from backend.app.data_store import DataStore  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.model_service import ModelService  # noqa: E402
from backend.app.pipeline import Services  # noqa: E402

FEST, ORIGIN = "FEST-2025-05", "2025-11-16T21:00:00"


@pytest.fixture(scope="session")
def settings():
    return Settings(llm_provider="none", anthropic_api_key="", ops=OpsConfig())


@pytest.fixture(scope="session")
def svc(settings):
    return Services(DataStore(DATA_PATH), ModelService(MODEL_PATH), settings)


@pytest.fixture(scope="session")
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture()
def ctx_body():
    return dict(festival_id=FEST, forecast_origin=ORIGIN, horizon_steps=8)
