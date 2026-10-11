"""Loads the persisted scikit-learn pipeline and produces recursive multi-step forecasts."""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from backend.app.errors import ServiceError
from ml.features import FEATURES, build_features


class ModelService:
    def __init__(self, path: Path, auto_train: bool = False):
        self.path = path
        self.pipeline = None
        self.metadata: dict = {}
        self.load_error: str | None = None
        self._load()
        if not self.loaded and auto_train:
            # Missing file or scikit-learn version mismatch: rebuild the model for THIS machine (about a minute).
            print("Model artefact unusable (%s) - retraining once, please wait..." % self.load_error, flush=True)
            try:
                from ml import train
                train.main()
                self._load()
            except BaseException as exc:  # noqa: BLE001 - never stop the API from starting
                self.load_error = f"Automatic retraining failed ({type(exc).__name__}: {exc}). Run: python -m ml.train"

    def _load(self) -> None:
        self.load_error = None
        try:
            art = joblib.load(self.path)
            self.pipeline, self.metadata = art["pipeline"], art["metadata"]
        except FileNotFoundError:
            self.load_error = f"Model artefact not found at {self.path}. Run: python -m ml.train"
        except Exception as exc:  # corrupted / version mismatch
            self.load_error = f"Model artefact could not be loaded ({type(exc).__name__}: {exc}). Re-run: python -m ml.train"

    @property
    def loaded(self) -> bool:
        return self.pipeline is not None

    def require(self) -> None:
        if not self.loaded:
            raise ServiceError(503, self.load_error or "Model not loaded", "model_unavailable")

    def role_of(self, festival_id: str) -> str:
        return self.metadata.get("split", {}).get("festival_roles", {}).get(festival_id, "unknown")

    def predict(self, window: pd.DataFrame) -> pd.DataFrame:
        """window: rows for all stops and steps (columns from add_derived + `step`). Adds pred/interval columns.

        Recursion: step 1 uses the observed previous-slot count; step h uses the prediction of step h-1.
        """
        self.require()
        d = window.sort_values(["step", "stop_id"]).reset_index(drop=True)
        feats = build_features(d)
        feats["step"] = d["step"].values
        feats["stop_key"] = d["stop_id"].values
        pred = np.zeros(len(d))
        lag_by_stop: dict[str, float] = {}
        for step in sorted(d["step"].unique()):
            idx = np.where(d["step"].values == step)[0]
            X = feats.iloc[idx][FEATURES].copy()
            if step == 1:
                lag_by_stop = dict(zip(d.iloc[idx]["stop_id"], X["lag_passengers"].astype(float)))
            X["lag_passengers"] = [lag_by_stop[s] for s in d.iloc[idx]["stop_id"]]
            p = np.maximum(self.pipeline.predict(X), 0.0)
            pred[idx] = p
            lag_by_stop = dict(zip(d.iloc[idx]["stop_id"], p))
        d["pred"] = pred
        iv = self.metadata.get("intervals", {})
        lo, hi = [], []
        for p, s in zip(d["pred"], d["step"]):
            q = iv.get(str(int(s)), iv.get("12", {"q10": -0.5, "q90": 0.5}))
            scale = max(p, 10.0)
            lo.append(max(p + scale * q["q10"], 0.0))
            hi.append(p + scale * q["q90"])
        d["lo"], d["hi"] = lo, hi
        return d
