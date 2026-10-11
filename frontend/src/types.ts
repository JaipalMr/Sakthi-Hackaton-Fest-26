export type RiskLevel = "low" | "elevated" | "high";

export interface Scenario {
  festival_end_shift_min: number;
  rainfall_mm_per_hr: number | null;
  bus_availability_factor: number;
  closed_stop_ids: string[];
}
export const BASELINE: Scenario = { festival_end_shift_min: 0, rainfall_mm_per_hr: null, bus_availability_factor: 1, closed_stop_ids: [] };
export const isBaseline = (s: Scenario) =>
  s.festival_end_shift_min === 0 && s.rainfall_mm_per_hr === null && s.bus_availability_factor === 1 && s.closed_stop_ids.length === 0;

export interface Health {
  status: "ok" | "degraded"; version: string; time_utc: string; dataset_loaded: boolean; dataset_rows: number;
  model_loaded: boolean; llm_mode: "live" | "demo"; llm_provider: string | null; llm_model?: string | null; details: string[];
}
export interface Slotted { date: string; festival_day: number; scheduled_start: string; scheduled_end: string; slots: string[] }
export interface Festival { festival_id: string; name: string; attendance: number; days: Slotted[]; split_role: string }
export interface FestivalsResponse { festivals: Festival[]; slot_minutes: number; data_is_synthetic: boolean }
export interface Stop { stop_id: string; stop_name: string; latitude: number; longitude: number; role: string; waiting_capacity: number; max_buses: number; typical_bus_capacity: number }
export interface StopsResponse { stops: Stop[]; travel_minutes: { origin: string; destination: string; minutes: number }[]; note: string }
export interface HorizonMetric { horizon: number; model_mae: number; model_rmse: number; persistence_mae: number; interval_empirical_coverage_test: number }
export interface MetricsResponse {
  model: { selected: string; trained_at_utc: string; test_one_step: { mae: number; rmse: number };
    baselines: Record<string, { description: string; test: { mae: number; rmse: number } }>; horizon_metrics: HorizonMetric[] };
  dataset: { rows: number; festivals: number; stops: number; synthetic: boolean; note: string };
  limitations: string[];
}
export interface StepForecast {
  step: number; timestamp: string; predicted_demand: number; interval_low: number; interval_high: number;
  actual_demand_synthetic: number | null; available_buses: number; average_bus_capacity: number; route_travel_time: number;
  rainfall: number; route_closed: boolean; event_phase: string; minutes_to_event_end: number; service_capacity: number;
  load_ratio: number; projected_backlog: number; crowding_ratio: number; risk_level: RiskLevel;
}
export interface StopForecast { stop_id: string; stop_name: string; latitude: number; longitude: number; role: string; waiting_capacity: number; steps: StepForecast[]; peak_risk_level: RiskLevel; peak_step: number; total_predicted_demand: number }
export interface TotalStep { step: number; timestamp: string; predicted_demand: number; actual_demand_synthetic: number | null; service_capacity: number; available_buses: number }
export interface PredictResponse {
  festival_id: string; festival_name: string; forecast_origin: string; horizon_steps_requested: number; horizon_steps_returned: number;
  model: { name: string; trained_at_utc: string; festival_split_role: string; in_sample: boolean; test_mae: number; test_rmse: number; baseline_persistence_test_mae: number; interval_method: string };
  provenance: { dataset: string; data_is_synthetic: boolean; scenario_applied: boolean; legend: Record<string, string>; warnings: string[] };
  forecasts: StopForecast[]; totals_by_step: TotalStep[]; limitations: string[];
}
export interface StopRiskView { stop_id: string; stop_name: string; buses: number; predicted_demand: number; service_capacity: number; unserved: number; load_ratio: number; crowding_ratio: number; risk_level: RiskLevel }
export interface ConstraintCheck { name: string; satisfied: boolean; detail: string }
export interface Recommendation { rank: number; origin_stop_id: string; origin_stop_name: string; destination_stop_id: string; destination_stop_name: string; buses: number; travel_time_min: number; rationale: string; constraints: ConstraintCheck[]; estimated_impact: Record<string, number> }
export interface OptimiseResponse {
  festival_id: string; target_step: number; target_timestamp: string; lead_time_min: number; status: "advisory"; requires_human_approval: boolean; approval_notice: string;
  config_used: Record<string, number>; before: StopRiskView[]; after: StopRiskView[]; recommendations: Recommendation[];
  unresolved: { stop_id: string; stop_name: string; remaining_unserved: number; reason: string }[];
  summary: { total_buses: number; buses_moved: number; unserved_before: number; unserved_after: number; additional_passengers_served: number; served_share_before: number; served_share_after: number; high_risk_stops_before: number; high_risk_stops_after: number };
  constraint_audit: ConstraintCheck[]; assumptions: string[]; warnings: string[];
}
export interface ScenarioStopDelta { stop_id: string; stop_name: string; baseline_demand: number; scenario_demand: number; baseline_buses: number; scenario_buses: number; baseline_risk: RiskLevel; scenario_risk: RiskLevel; baseline_load_ratio: number; scenario_load_ratio: number }
export interface SimulateResponse {
  scenario: Scenario; labels: Record<string, string>; warnings: string[]; baseline_totals: TotalStep[]; scenario_totals: TotalStep[];
  stop_deltas: ScenarioStopDelta[]; baseline_optimisation: OptimiseResponse; scenario_optimisation: OptimiseResponse; headline: Record<string, number>;
}
export interface ToolCallRecord { name: string; arguments: Record<string, unknown>; ok: boolean; error: string | null }
export interface AssistantResponse { answer: string; mode: "live_llm" | "demo"; provider: string | null; model: string | null; fallback_reason: string | null; tool_calls: ToolCallRecord[]; warnings: string[]; disclaimer: string }
export interface ForecastParams { festival_id: string; forecast_origin: string; horizon_steps: number }

export interface BriefingRisk { stop_id: string; stop_name: string; risk: RiskLevel; peak_demand: number; service_capacity: number; peak_time: string }
export interface BriefingMove { from_stop: string; to_stop: string; buses: number; travel_min: number }
export interface BriefingResponse {
  headline: string; narrative: string; mode: "live_llm" | "demo"; provider: string | null; model: string | null; fallback_reason: string | null;
  top_risks: BriefingRisk[]; moves: BriefingMove[]; unserved_before: number; unserved_after: number; warnings: string[]; disclaimer: string;
}

export interface ChaosResult { id: string; category: "weather" | "schedule" | "fleet" | "closure" | "compound"; label: string; weight: number; unserved_after: number; extra_unserved: number; harm: number; worst_time: string; high_risk_stops_after: number; buses_moved: number; status: "coped" | "strained" | "critical" }
export interface ChaosResponse {
  score: number; grade: string; slots_tested: string[]; baseline_unserved_after: number; results: ChaosResult[]; weakest_link: ChaosResult; worst_case: ChaosResult;
  hardening_tips: string[]; method: string; narrative: string; mode: "live_llm" | "demo"; provider: string | null; model: string | null; fallback_reason: string | null; warnings: string[]; disclaimer: string;
}
export type LangCode = "en" | "hi" | "ta" | "es";
export interface Announcement { lang: LangCode; language: string; speech_lang: string; text: string; source: "llm" | "template" }
export interface AnnouncementResponse {
  situation: string; crowded_stop: string | null; alternative_stop: string | null; wait_minutes: number | null; announcements: Announcement[];
  mode: "live_llm" | "demo"; provider: string | null; model: string | null; fallback_reason: string | null; disclaimer: string;
}
