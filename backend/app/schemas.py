"""Pydantic request/response schemas for every endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RiskLevel = Literal["low", "elevated", "high"]


# ------------------------------------------------------------------ requests ------------------
class Scenario(BaseModel):
    """What-if assumptions. These are SIMULATED ASSUMPTIONS, not observed data."""
    model_config = ConfigDict(extra="forbid")
    festival_end_shift_min: int = Field(0, ge=-60, le=60, description="shift scheduled festival end (minutes)")
    rainfall_mm_per_hr: float | None = Field(None, ge=0, le=30, description="override rainfall for all forecast slots")
    bus_availability_factor: float = Field(1.0, ge=0.0, le=1.5, description="scale available buses at every stop")
    closed_stop_ids: list[str] = Field(default_factory=list, max_length=10)

    def is_baseline(self) -> bool:
        return (self.festival_end_shift_min == 0 and self.rainfall_mm_per_hr is None
                and self.bus_availability_factor == 1.0 and not self.closed_stop_ids)


class ForecastContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    festival_id: str = Field(min_length=3, max_length=40)
    forecast_origin: datetime = Field(description="start of the first forecast slot (local time, no timezone)")
    horizon_steps: int = Field(8, ge=1, le=12, description="number of 15-minute slots to forecast")
    stop_ids: list[str] | None = Field(None, max_length=10)

    @field_validator("forecast_origin")
    @classmethod
    def _naive(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            raise ValueError("forecast_origin must be a local time without timezone offset, e.g. 2025-11-15T21:00:00")
        return v


class PredictRequest(ForecastContext):
    scenario: Scenario | None = None


class OpsOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reserve_margin: float | None = Field(None, ge=0, le=0.5)
    dispatch_buffer_min: float | None = Field(None, ge=0, le=30)
    min_buses_per_stop: int | None = Field(None, ge=0, le=10)
    max_moves: int | None = Field(None, ge=1, le=50)


class OptimiseRequest(ForecastContext):
    target_step: int = Field(3, ge=1, le=12, description="forecast step whose demand the allocation targets")
    overrides: OpsOverrides | None = None
    scenario: Scenario | None = None


class SimulateRequest(ForecastContext):
    target_step: int = Field(3, ge=1, le=12)
    overrides: OpsOverrides | None = None
    scenario: Scenario


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AssistantContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    festival_id: str
    forecast_origin: datetime
    horizon_steps: int = Field(8, ge=1, le=12)
    target_step: int = Field(3, ge=1, le=12)
    scenario: Scenario | None = None

    @field_validator("forecast_origin")
    @classmethod
    def _naive(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            raise ValueError("forecast_origin must not carry a timezone offset")
        return v


class AssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context: AssistantContext
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)


class BriefingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: AssistantContext


# ------------------------------------------------------------------ responses -----------------
class StepForecast(BaseModel):
    step: int
    timestamp: datetime
    predicted_demand: float
    interval_low: float
    interval_high: float
    actual_demand_synthetic: float | None = Field(None, description="synthetic label from the dataset; null in what-if scenarios")
    available_buses: int
    average_bus_capacity: int
    route_travel_time: float
    rainfall: float
    route_closed: bool
    event_phase: str
    minutes_to_event_end: float
    service_capacity: float
    load_ratio: float
    projected_backlog: float
    crowding_ratio: float
    risk_level: RiskLevel


class StopForecast(BaseModel):
    stop_id: str
    stop_name: str
    latitude: float
    longitude: float
    role: str
    waiting_capacity: int
    steps: list[StepForecast]
    peak_risk_level: RiskLevel
    peak_step: int
    total_predicted_demand: float


class TotalStep(BaseModel):
    step: int
    timestamp: datetime
    predicted_demand: float
    actual_demand_synthetic: float | None
    service_capacity: float
    available_buses: int


class ModelInfo(BaseModel):
    name: str
    trained_at_utc: str
    festival_split_role: Literal["train", "validation", "test", "unknown"]
    in_sample: bool
    test_mae: float
    test_rmse: float
    baseline_persistence_test_mae: float
    interval_method: str


class Provenance(BaseModel):
    dataset: str
    data_is_synthetic: bool = True
    scenario_applied: bool
    scenario: Scenario | None
    legend: dict[str, str]
    warnings: list[str] = Field(default_factory=list)


class PredictResponse(BaseModel):
    festival_id: str
    festival_name: str
    forecast_origin: datetime
    horizon_steps_requested: int
    horizon_steps_returned: int
    slot_minutes: int = 15
    model: ModelInfo
    provenance: Provenance
    forecasts: list[StopForecast]
    totals_by_step: list[TotalStep]
    limitations: list[str]


class StopRiskView(BaseModel):
    stop_id: str
    stop_name: str
    buses: int
    predicted_demand: float
    service_capacity: float
    unserved: float
    load_ratio: float
    crowding_ratio: float
    risk_level: RiskLevel


class ConstraintCheck(BaseModel):
    name: str
    satisfied: bool
    detail: str


class Recommendation(BaseModel):
    rank: int
    origin_stop_id: str
    origin_stop_name: str
    destination_stop_id: str
    destination_stop_name: str
    buses: int
    travel_time_min: float
    rationale: str
    constraints: list[ConstraintCheck]
    estimated_impact: dict[str, float]


class UnresolvedStop(BaseModel):
    stop_id: str
    stop_name: str
    remaining_unserved: float
    reason: str


class OptimiseSummary(BaseModel):
    total_buses: int
    buses_moved: int
    unserved_before: float
    unserved_after: float
    additional_passengers_served: float
    served_share_before: float
    served_share_after: float
    high_risk_stops_before: int
    high_risk_stops_after: int


class OptimiseResponse(BaseModel):
    festival_id: str
    forecast_origin: datetime
    target_step: int
    target_timestamp: datetime
    lead_time_min: float
    status: Literal["advisory"] = "advisory"
    requires_human_approval: bool = True
    approval_notice: str
    config_used: dict[str, float | int]
    scenario_applied: bool
    before: list[StopRiskView]
    after: list[StopRiskView]
    recommendations: list[Recommendation]
    unresolved: list[UnresolvedStop]
    summary: OptimiseSummary
    constraint_audit: list[ConstraintCheck]
    assumptions: list[str]
    warnings: list[str] = Field(default_factory=list)


class ScenarioStopDelta(BaseModel):
    stop_id: str
    stop_name: str
    baseline_demand: float
    scenario_demand: float
    baseline_buses: int
    scenario_buses: int
    baseline_risk: RiskLevel
    scenario_risk: RiskLevel
    baseline_load_ratio: float
    scenario_load_ratio: float


class SimulateResponse(BaseModel):
    festival_id: str
    forecast_origin: datetime
    target_step: int
    scenario: Scenario
    labels: dict[str, str]
    warnings: list[str]
    baseline_totals: list[TotalStep]
    scenario_totals: list[TotalStep]
    stop_deltas: list[ScenarioStopDelta]
    baseline_optimisation: OptimiseResponse
    scenario_optimisation: OptimiseResponse
    headline: dict[str, float]


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict
    ok: bool
    error: str | None = None


class AssistantResponse(BaseModel):
    answer: str
    mode: Literal["live_llm", "demo"]
    provider: str | None
    model: str | None
    fallback_reason: str | None = None
    tool_calls: list[ToolCallRecord]
    grounding: dict = Field(default_factory=dict, description="compact backend outputs the answer is based on")
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str


class BriefingRisk(BaseModel):
    stop_id: str
    stop_name: str
    risk: str
    peak_demand: float
    service_capacity: float
    peak_time: str


class BriefingMove(BaseModel):
    from_stop: str
    to_stop: str
    buses: int
    travel_min: float


class BriefingResponse(BaseModel):
    headline: str
    narrative: str
    mode: Literal["live_llm", "demo"]
    provider: str | None
    model: str | None
    fallback_reason: str | None = None
    top_risks: list[BriefingRisk]
    moves: list[BriefingMove]
    unserved_before: float
    unserved_after: float
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str


class ChaosRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: AssistantContext


class ChaosResult(BaseModel):
    id: str
    category: Literal["weather", "schedule", "fleet", "closure", "compound"]
    label: str
    weight: float
    unserved_after: float
    extra_unserved: float
    harm: float
    worst_time: str
    high_risk_stops_after: int
    buses_moved: int
    status: Literal["coped", "strained", "critical"]


class ChaosResponse(BaseModel):
    score: int
    grade: str
    slots_tested: list[str]
    baseline_unserved_after: float
    results: list[ChaosResult]
    weakest_link: ChaosResult
    worst_case: ChaosResult
    hardening_tips: list[str]
    method: str
    narrative: str
    mode: Literal["live_llm", "demo"]
    provider: str | None
    model: str | None
    fallback_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str


class AnnouncementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: AssistantContext
    languages: list[Literal["en", "hi", "ta", "es"]] = Field(default_factory=lambda: ["en", "hi", "ta"], min_length=1, max_length=4)


class Announcement(BaseModel):
    lang: str
    language: str
    speech_lang: str
    text: str
    source: Literal["llm", "template"]


class AnnouncementResponse(BaseModel):
    situation: str
    crowded_stop: str | None
    alternative_stop: str | None
    wait_minutes: int | None
    announcements: list[Announcement]
    mode: Literal["live_llm", "demo"]
    provider: str | None
    model: str | None
    fallback_reason: str | None = None
    disclaimer: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    time_utc: str
    dataset_loaded: bool
    dataset_rows: int
    model_loaded: bool
    llm_mode: Literal["live", "demo"]
    llm_provider: str | None
    llm_model: str | None = None
    details: list[str] = Field(default_factory=list)
