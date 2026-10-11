"""Crowd-risk assessment. Thresholds are configurable OPERATIONAL ASSUMPTIONS (see config.OpsConfig)."""
from __future__ import annotations

from backend.app.config import OpsConfig

LEVELS = ["low", "elevated", "high"]


def level_index(level: str) -> int:
    return LEVELS.index(level)


def assess(demand: float, service: float, backlog_in: float, waiting_capacity: float, ops: OpsConfig) -> dict:
    """Return load ratio, end-of-slot queue estimate, crowding ratio and a risk level."""
    load = 99.0 if service <= 1e-9 and demand > 0 else (demand / service if service > 1e-9 else 0.0)
    load = min(load, 99.0)
    queue_end = max(0.0, backlog_in + demand - service)
    crowd = queue_end / max(waiting_capacity, 1.0)
    if load >= ops.load_high or crowd >= ops.crowd_high:
        level = "high"
    elif load >= ops.load_elevated or crowd >= ops.crowd_elevated:
        level = "elevated"
    else:
        level = "low"
    return dict(load_ratio=round(load, 3), unserved=round(max(0.0, demand - service), 1),
                projected_backlog=round(queue_end, 1), crowding_ratio=round(crowd, 3), risk_level=level)
