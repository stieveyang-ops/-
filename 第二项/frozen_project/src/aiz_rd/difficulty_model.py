"""Stage 8 ordinal reaction-difficulty model."""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.miscmodels.ordinal_model import OrderedModel


class ReactionDifficultyModel:
    FEATURE_ORDER = ("d_feas", "d_prec", "d_sc")
    LABEL_ORDER = (0, 1, 2)

    def __init__(self):
        self.result = None
        self.converged = False

    @staticmethod
    def _validate_x(X):
        if not isinstance(X, pd.DataFrame):
            raise TypeError("X must be a pandas DataFrame")
        if X.columns.tolist() != list(ReactionDifficultyModel.FEATURE_ORDER):
            raise ValueError(f"X columns must be exactly {list(ReactionDifficultyModel.FEATURE_ORDER)}")
        values = X.to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError("model features must be finite and in [0,1]")
        return X.astype(float)

    @staticmethod
    def _validate_y(y):
        values = np.asarray(y, dtype=int)
        if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
            raise ValueError("y must be a non-empty finite vector")
        if not set(values.tolist()).issubset(set(ReactionDifficultyModel.LABEL_ORDER)):
            raise ValueError("y must contain only ordered labels 0,1,2")
        if set(values.tolist()) != set(ReactionDifficultyModel.LABEL_ORDER):
            raise ValueError("all three ordered labels are required for fitting")
        return values

    def fit(self, X, y):
        X = self._validate_x(X)
        y = self._validate_y(y)
        # OrderedModel requires identically aligned pandas indices.
        X = X.reset_index(drop=True)
        model = OrderedModel(pd.Series(y, name="expert_label"), X, distr="logit")
        result = model.fit(method="bfgs", maxiter=1000, disp=False)
        converged = bool(result.mle_retvals.get("converged", False))
        params = np.asarray(result.params, dtype=float)
        if not converged or not np.isfinite(params).all():
            raise RuntimeError("OrderedModel did not converge with finite parameters")
        probabilities = np.asarray(result.model.predict(result.params, exog=X), dtype=float)
        if probabilities.shape != (len(X), 3) or not np.isfinite(probabilities).all():
            raise RuntimeError("OrderedModel probability output is invalid")
        if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-10, rtol=0):
            raise RuntimeError("OrderedModel probabilities do not sum to one")
        self.result = result
        self.converged = converged
        return self

    def _require_fitted(self):
        if self.result is None:
            raise RuntimeError("model is not fitted")

    def predict_proba(self, X):
        self._require_fitted()
        X = self._validate_x(X)
        probabilities = np.asarray(self.result.model.predict(self.result.params, exog=X), dtype=float)
        if probabilities.shape != (len(X), 3) or not np.isfinite(probabilities).all():
            raise RuntimeError("invalid probability output")
        if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-10, rtol=0):
            raise RuntimeError("probabilities do not sum to one")
        return probabilities

    def predict_difficulty(self, X):
        probabilities = self.predict_proba(X)
        difficulty = 50.0 * probabilities[:, 1] + 100.0 * probabilities[:, 2]
        if not np.isfinite(difficulty).all() or ((difficulty < 0) | (difficulty > 100)).any():
            raise RuntimeError("difficulty outside [0,100]")
        return difficulty

    def metadata_parameters(self):
        self._require_fitted()
        params = self.result.params
        return {str(k): float(v) for k, v in params.items()}

    def save(self, path, metadata_path, metadata):
        self._require_fitted()
        path = Path(path)
        metadata_path = Path(metadata_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("wb") as handle:
            pickle.dump(self, handle, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        import json
        mtmp = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
        mtmp.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        mtmp.replace(metadata_path)

    @classmethod
    def load(cls, path, metadata_path=None):
        with Path(path).open("rb") as handle:
            model = pickle.load(handle)
        if not isinstance(model, cls):
            raise TypeError("serialized object is not ReactionDifficultyModel")
        return model
