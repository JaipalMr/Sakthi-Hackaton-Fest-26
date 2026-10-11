"""Environment-driven settings. Secrets are read from the environment only (never hard-coded)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "festival_transport_demand.csv"
MODEL_PATH = ROOT / "ml" / "artifacts" / "demand_model.joblib"
APP_VERSION = "0.3.0"


def load_dotenv(path: Path | None = None) -> None:
    """Tiny .env loader (no extra dependency). Existing environment variables win."""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.split("#", 1)[0].strip().strip('"').strip("'"))


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class OpsConfig:
    """OPERATIONAL ASSUMPTIONS - configurable policy knobs, not universal crowd-safety thresholds."""
    load_elevated: float = 0.90      # predicted demand / service capacity
    load_high: float = 1.15
    crowd_elevated: float = 0.50     # projected waiting people / stop waiting capacity
    crowd_high: float = 0.80
    reserve_margin: float = 0.10     # donor must keep service >= demand * (1 + margin)
    dispatch_buffer_min: float = 5.0  # minutes needed to brief/dispatch before a move can start
    min_buses_per_stop: int = 1
    max_moves: int = 20

    @staticmethod
    def from_env() -> "OpsConfig":
        return OpsConfig(
            load_elevated=_f("OPS_LOAD_ELEVATED", 0.90), load_high=_f("OPS_LOAD_HIGH", 1.15),
            crowd_elevated=_f("OPS_CROWD_ELEVATED", 0.50), crowd_high=_f("OPS_CROWD_HIGH", 0.80),
            reserve_margin=_f("OPS_RESERVE_MARGIN", 0.10), dispatch_buffer_min=_f("OPS_DISPATCH_BUFFER_MIN", 5.0),
            min_buses_per_stop=int(_f("OPS_MIN_BUSES_PER_STOP", 1)), max_moves=int(_f("OPS_MAX_MOVES", 20)))


@dataclass(frozen=True)
class Settings:
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    llm_provider: str = "none"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""      # e.g. http://localhost:11434/v1 for Ollama; empty = api.openai.com
    llm_model: str = "claude-sonnet-5-5"
    llm_timeout: float = 25.0
    llm_max_rounds: int = 4
    ops: OpsConfig = field(default_factory=OpsConfig)

    @property
    def llm_live(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":  # local OpenAI-compatible servers (Ollama, LM Studio) need no key but need a base URL
            return bool(self.openai_api_key or self.openai_base_url)
        return False


def get_settings() -> Settings:
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
    return Settings(
        cors_origins=origins,
        llm_provider=os.environ.get("LLM_PROVIDER", "none").strip().lower(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "").strip(),
        llm_model=os.environ.get("LLM_MODEL", "claude-sonnet-5-5").strip(),
        llm_timeout=_f("LLM_TIMEOUT_SECONDS", 25.0),
        llm_max_rounds=int(_f("LLM_MAX_TOOL_ROUNDS", 4)),
        ops=OpsConfig.from_env(),
    )
