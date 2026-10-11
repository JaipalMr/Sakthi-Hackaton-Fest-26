"""Recursive multi-step forecasting with a one-step-ahead model.

Step 1 uses the true observed passenger count of the previous slot as `lag_passengers`.
Step h>1 feeds the model's own prediction for step h-1 (no future demand is ever used).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.features import FEATURES, TARGET, build_features, series_key


def recursive_forecast(pipe, feat_future: pd.DataFrame) -> np.ndarray:
    """feat_future: feature rows for steps 1..H of ONE stop; row 0's lag must be the observed value."""
    preds = np.zeros(len(feat_future))
    lag = float(feat_future["lag_passengers"].iloc[0])
    for i in range(len(feat_future)):
        row = feat_future.iloc[[i]].copy()
        row["lag_passengers"] = lag
        p = float(max(pipe.predict(row[FEATURES])[0], 0.0))
        preds[i] = p
        lag = p
    return preds


def horizon_predictions(pipe, df: pd.DataFrame, max_h: int = 12) -> dict[int, pd.DataFrame]:
    """Vectorised recursive evaluation for every (series, origin) pair.

    Returns {h: DataFrame(pred, actual, persistence)} where h-th step target is origin_row + h - 1.
    """
    d = df.sort_values(["festival_id", "stop_id", "timestamp"]).reset_index(drop=True)
    feats = build_features(d)
    key = series_key(d).values
    pos = d.groupby(key).cumcount().values
    size = pd.Series(key).map(pd.Series(key).value_counts()).values
    actual = d[TARGET].values.astype(float)
    lag_all = feats["lag_passengers"].values.astype(float)
    idx = np.arange(len(d))
    alive = np.ones(len(d), dtype=bool)
    lag_vec = lag_all.copy()           # lag for step 1 = true lag of the origin row
    persistence = lag_all.copy()
    out: dict[int, pd.DataFrame] = {}
    for h in range(1, max_h + 1):
        alive &= (pos + h - 1) < size
        if not alive.any():
            break
        tgt = idx + h - 1
        sel = np.where(alive)[0]
        X = feats.iloc[tgt[sel]].copy()
        X["lag_passengers"] = lag_vec[sel]
        p = np.maximum(pipe.predict(X[FEATURES]), 0.0)
        out[h] = pd.DataFrame({"pred": p, "actual": actual[tgt[sel]], "persistence": persistence[sel],
                               "origin_row": sel})
        lag_vec = lag_vec.copy()
        lag_vec[sel] = p
    return out
