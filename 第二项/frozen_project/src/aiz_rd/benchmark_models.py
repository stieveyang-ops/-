"""Stage 10 development-only comparator models.

The public fitting API accepts one development DataFrame only.  Locked-test
rows are intentionally never accepted by the fit functions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from statsmodels.miscmodels.ordinal_model import OrderedModel


LABELS = (0, 1, 2)
FEATURE_A = ("d_feas",)
FEATURE_B = ("d_prec",)
FEATURE_C = ("d_sc",)
FEATURE_E = ("difficulty_dev",)


def _validate_development_frame(dev_df: pd.DataFrame, features: Sequence[str]) -> tuple[pd.DataFrame, np.ndarray]:
    if not isinstance(dev_df, pd.DataFrame):
        raise TypeError("dev_df must be a pandas DataFrame")
    required = list(features) + ["expert_label"]
    missing = [c for c in required if c not in dev_df.columns]
    if missing:
        raise ValueError(f"development frame missing columns: {missing}")
    if dev_df.empty:
        raise ValueError("development frame is empty")
    x = dev_df[list(features)].astype(float)
    if not np.isfinite(x.to_numpy()).all():
        raise ValueError("development features contain NaN/Inf")
    y = dev_df["expert_label"].astype(int).to_numpy()
    if not set(y.tolist()).issubset(set(LABELS)) or set(y.tolist()) != set(LABELS):
        raise ValueError("development labels must contain exactly 0, 1, and 2")
    return x.reset_index(drop=True), y


@dataclass
class OrdinalBenchmarkModel:
    """A fixed-protocol ordinal logit model fitted on development rows."""

    features: tuple[str, ...]
    result: object | None = None
    converged: bool = False

    def fit(self, dev_df: pd.DataFrame) -> "OrdinalBenchmarkModel":
        x, y = _validate_development_frame(dev_df, self.features)
        model = OrderedModel(pd.Series(y, name="expert_label"), x, distr="logit")
        result = model.fit(method="bfgs", maxiter=1000, disp=False)
        params = np.asarray(result.params, dtype=float)
        self.converged = bool(result.mle_retvals.get("converged", False))
        if not self.converged or not np.isfinite(params).all():
            raise RuntimeError("OrderedModel did not converge with finite parameters")
        self.result = result
        # Validate the development probability contract immediately.
        self.predict_proba(dev_df)
        return self

    def _require(self) -> object:
        if self.result is None:
            raise RuntimeError("benchmark model is not fitted")
        return self.result

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        result = self._require()
        missing = [c for c in self.features if c not in df.columns]
        if missing:
            raise ValueError(f"prediction frame missing columns: {missing}")
        x = df[list(self.features)].astype(float)
        values = x.to_numpy()
        if not np.isfinite(values).all():
            raise ValueError("prediction features contain NaN/Inf")
        probabilities = np.asarray(result.model.predict(result.params, exog=x), dtype=np.float64)
        if probabilities.shape != (len(df), 3) or not np.isfinite(probabilities).all():
            raise RuntimeError("invalid ordinal probabilities")
        if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-10, rtol=0.0):
            raise RuntimeError("ordinal probabilities do not sum to one")
        if ((probabilities < 0.0) | (probabilities > 1.0)).any():
            raise RuntimeError("ordinal probabilities outside [0,1]")
        return probabilities

    def predict_frame(self, df: pd.DataFrame, prefix: str) -> pd.DataFrame:
        probabilities = self.predict_proba(df)
        classes = np.argmax(probabilities, axis=1).astype(int)
        difficulty = 50.0 * probabilities[:, 1] + 100.0 * probabilities[:, 2]
        if not np.isfinite(difficulty).all() or ((difficulty < 0.0) | (difficulty > 100.0)).any():
            raise RuntimeError("difficulty outside [0,100]")
        return pd.DataFrame(
            {
                f"{prefix}_p_easy": probabilities[:, 0],
                f"{prefix}_p_medium": probabilities[:, 1],
                f"{prefix}_p_difficult": probabilities[:, 2],
                f"{prefix}_class": classes,
                f"{prefix}_difficulty": difficulty,
            },
            index=df.index,
        )

    def metadata(self) -> dict[str, object]:
        result = self._require()
        params = {str(k): float(v) for k, v in result.params.items()}
        return {
            "features": list(self.features),
            "distribution": "logit",
            "optimizer": "bfgs + maxiter=1000",
            "converged": bool(self.converged),
            "parameters": params,
            "label_order": {"0": "Easy", "1": "Medium", "2": "Difficult"},
        }


def fit_model_A(dev_df: pd.DataFrame) -> OrdinalBenchmarkModel:
    return OrdinalBenchmarkModel(FEATURE_A).fit(dev_df)


def fit_model_B(dev_df: pd.DataFrame) -> OrdinalBenchmarkModel:
    return OrdinalBenchmarkModel(FEATURE_B).fit(dev_df)


def fit_model_C(dev_df: pd.DataFrame) -> OrdinalBenchmarkModel:
    return OrdinalBenchmarkModel(FEATURE_C).fit(dev_df)


def fit_model_E(dev_df: pd.DataFrame) -> OrdinalBenchmarkModel:
    return OrdinalBenchmarkModel(FEATURE_E).fit(dev_df)


def fit_model_features(dev_df: pd.DataFrame, features: Sequence[str]) -> OrdinalBenchmarkModel:
    return OrdinalBenchmarkModel(tuple(features)).fit(dev_df)


def model_metadata_json(model: OrdinalBenchmarkModel) -> str:
    return json.dumps(model.metadata(), sort_keys=True, ensure_ascii=False)
