"""Train, compare and persist the demand model.  Usage: python -m ml.train

Protocol (all time-aware; every split boundary falls between festivals, so evaluation is on FUTURE editions):
  1. chronological split by unique timestamp: 60% train / 20% validation / 20% test
  2. baselines: persistence (previous-slot count) and training mean by stop x event_phase
  3. candidates (HistGradientBoosting, RandomForest) fit on TRAIN only, chosen by VALIDATION RMSE
  4. chosen model is refit on TRAIN+VALIDATION, then evaluated ONCE on the held-out TEST set
  5. recursive multi-step residuals on validation define prediction intervals; test coverage is reported
All numbers are measured on SYNTHETIC data; they do NOT describe real-world accuracy.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from ml.features import CATEGORICAL, FEATURES, NUMERIC, TARGET, build_features
from ml.forecast import horizon_predictions
from ml.network import FESTIVAL_NAMES

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "festival_transport_demand.csv"
ART_DIR = ROOT / "ml" / "artifacts"
MODEL_PATH = ART_DIR / "demand_model.joblib"
METRICS_PATH = ART_DIR / "metrics.json"
MAX_H = 12
SEED = 42


def mae(y, p): return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))
def rmse(y, p): return float(np.sqrt(np.mean((np.asarray(y) - np.asarray(p)) ** 2)))


def make_pipeline(kind: str) -> Pipeline:
    pre = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL)],
        remainder="passthrough", verbose_feature_names_out=False)
    if kind == "hist_gradient_boosting":
        est = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, max_leaf_nodes=24,
                                            min_samples_leaf=20, l2_regularization=1.0, random_state=SEED)
    elif kind == "random_forest":
        est = RandomForestRegressor(n_estimators=200, min_samples_leaf=3, n_jobs=-1, random_state=SEED)
    else:
        raise ValueError(kind)
    return Pipeline([("prep", pre), ("model", est)])


def chronological_split(df: pd.DataFrame):
    ts = np.sort(df["timestamp"].unique())
    n = len(ts)
    c1, c2 = ts[int(n * 0.6)], ts[int(n * 0.8)]
    tr, va, te = df[df["timestamp"] < c1], df[(df["timestamp"] >= c1) & (df["timestamp"] < c2)], df[df["timestamp"] >= c2]
    assert tr["timestamp"].max() < va["timestamp"].min() <= va["timestamp"].max() < te["timestamp"].min()
    return tr, va, te


def main() -> int:
    if not DATA.exists():
        print("Dataset missing. Run: python -m ml.generate_dataset"); return 1
    df = pd.read_csv(DATA)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values(["timestamp", "stop_id"]).reset_index(drop=True)
    train, val, test = chronological_split(df)
    print(f"split rows  train={len(train)}  val={len(val)}  test={len(test)}")
    roles = {}
    for name, part in [("train", train), ("validation", val), ("test", test)]:
        for f in part["festival_id"].unique():
            roles[f] = name

    Xtr, Xva, Xte = (build_features(p) for p in (train, val, test))
    ytr, yva, yte = train[TARGET].values, val[TARGET].values, test[TARGET].values

    # ---- baselines ---------------------------------------------------------------------------
    grp = train.groupby(["stop_id", "event_phase"])[TARGET].mean()
    def phase_mean(p):
        return np.array([grp.get((s, ph), train[TARGET].mean()) for s, ph in zip(p["stop_id"], p["event_phase"])])
    results = {
        "baseline_persistence": {
            "description": "predict the previous slot's observed passenger count",
            "val": dict(mae=mae(yva, Xva["lag_passengers"]), rmse=rmse(yva, Xva["lag_passengers"])),
            "test": dict(mae=mae(yte, Xte["lag_passengers"]), rmse=rmse(yte, Xte["lag_passengers"]))},
        "baseline_stop_phase_mean": {
            "description": "training-set mean demand per stop x event phase",
            "val": dict(mae=mae(yva, phase_mean(val)), rmse=rmse(yva, phase_mean(val))),
            "test": dict(mae=mae(yte, phase_mean(test)), rmse=rmse(yte, phase_mean(test)))},
    }
    # ---- candidates (fit on TRAIN, compare on VALIDATION) ---------------------------------------
    cand = {}
    for kind in ["hist_gradient_boosting", "random_forest"]:
        pipe = make_pipeline(kind).fit(Xtr[FEATURES], ytr)
        pv = np.maximum(pipe.predict(Xva[FEATURES]), 0)
        cand[kind] = dict(pipe=pipe, val=dict(mae=mae(yva, pv), rmse=rmse(yva, pv)))
        print(f"{kind:24s} val MAE={cand[kind]['val']['mae']:.2f} RMSE={cand[kind]['val']['rmse']:.2f}")
    best = min(cand, key=lambda k: cand[k]["val"]["rmse"])
    print("selected:", best)

    # ---- recursive multi-step residuals on validation -> interval quantiles -----------------------
    val_h = horizon_predictions(cand[best]["pipe"], val, MAX_H)
    intervals = {}
    for h, r in val_h.items():
        rel = (r["actual"] - r["pred"]) / np.maximum(r["pred"], 10.0)
        intervals[h] = dict(q10=float(np.quantile(rel, 0.10)), q90=float(np.quantile(rel, 0.90)), n=int(len(rel)))

    # ---- refit on TRAIN+VAL, single evaluation on TEST --------------------------------------------
    final = make_pipeline(best).fit(pd.concat([Xtr, Xva])[FEATURES], np.concatenate([ytr, yva]))
    pt = np.maximum(final.predict(Xte[FEATURES]), 0)
    test_one_step = dict(mae=mae(yte, pt), rmse=rmse(yte, pt))
    test_h = horizon_predictions(final, test, MAX_H)
    horizons = []
    for h, r in test_h.items():
        iv = intervals[h]
        scale = np.maximum(r["pred"], 10.0)
        lo, hi = np.maximum(r["pred"] + scale * iv["q10"], 0), r["pred"] + scale * iv["q90"]
        horizons.append(dict(
            horizon=h, n=int(len(r)),
            model_mae=mae(r["actual"], r["pred"]), model_rmse=rmse(r["actual"], r["pred"]),
            persistence_mae=mae(r["actual"], r["persistence"]), persistence_rmse=rmse(r["actual"], r["persistence"]),
            interval_nominal_coverage=0.8,
            interval_empirical_coverage_test=float(np.mean((r["actual"] >= lo) & (r["actual"] <= hi)))))
    print(f"TEST one-step  MAE={test_one_step['mae']:.2f}  RMSE={test_one_step['rmse']:.2f}")
    print("persistence    MAE={mae:.2f}  RMSE={rmse:.2f}".format(**results["baseline_persistence"]["test"]))
    print("stop-phase mean MAE={mae:.2f}  RMSE={rmse:.2f}".format(**results["baseline_stop_phase_mean"]["test"]))

    metadata = dict(
        trained_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        sklearn_version=sklearn.__version__,
        selected_model=best,
        features=FEATURES,
        target=TARGET,
        data_is_synthetic=True,
        split=dict(method="chronological by unique timestamp (60/20/20); boundaries fall between festivals",
                   train_rows=len(train), validation_rows=len(val), test_rows=len(test),
                   festival_roles=roles,
                   festival_names={k: FESTIVAL_NAMES[k] for k in roles}),
        final_fit="selected model refit on train+validation; test set used once",
        baselines=results,
        candidates={k: dict(validation=v["val"]) for k, v in cand.items()},
        test_one_step=test_one_step,
        horizon_metrics=horizons,
        interval_method="empirical 10th/90th percentile of relative validation residuals per horizon "
                        "(recursive forecast); interval = pred +/- max(pred,10) * quantile; nominal 80%",
        intervals={str(h): v for h, v in intervals.items()},
        limitations=[
            "Trained and evaluated only on SYNTHETIC data; real-world accuracy is unknown.",
            "Only 5 simulated festivals: weak evidence of generalisation to new venues or event types.",
            "Future weather, fleet plan, route times and closures are treated as known inputs (perfect forecast).",
            "Multi-step forecasts are recursive; error grows with horizon.",
            "Intervals are empirical and approximate; they are not guaranteed coverage.",
        ],
    )
    ART_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(dict(pipeline=final, metadata=metadata), MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metadata, indent=2))
    print(f"saved model -> {MODEL_PATH}\nsaved metrics -> {METRICS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
