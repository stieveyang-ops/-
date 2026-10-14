"""Fixed Stage 10 benchmark metrics."""
from __future__ import annotations

import warnings

import numpy as np
from scipy.stats import kendalltau, spearmanr
from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score, confusion_matrix, f1_score


METRICS = ("kendall_tau_b", "spearman_rho", "macro_f1", "balanced_accuracy", "quadratic_weighted_kappa")


def compute_metrics(y_true, difficulty, predicted_class) -> dict[str, object]:
    y = np.asarray(y_true, dtype=int)
    d = np.asarray(difficulty, dtype=np.float64)
    pred = np.asarray(predicted_class, dtype=int)
    if not (len(y) == len(d) == len(pred)) or len(y) == 0:
        raise ValueError("metric inputs must have equal nonzero length")
    if not np.isfinite(d).all():
        raise ValueError("difficulty contains NaN/Inf")
    warnings_seen: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        kt = kendalltau(y, d, variant="b")
        sr = spearmanr(y, d)
        macro = f1_score(y, pred, average="macro", labels=[0, 1, 2], zero_division=0)
        bal = balanced_accuracy_score(y, pred)
        qwk = cohen_kappa_score(y, pred, labels=[0, 1, 2], weights="quadratic")
    warnings_seen.extend(f"{type(w.message).__name__}: {w.message}" for w in caught)
    cm = confusion_matrix(y, pred, labels=[0, 1, 2]).tolist()
    support = {str(k): int(np.sum(y == k)) for k in [0, 1, 2]}
    return {
        "kendall_tau_b": float(kt.statistic) if np.isfinite(kt.statistic) else np.nan,
        "kendall_pvalue": float(kt.pvalue) if np.isfinite(kt.pvalue) else np.nan,
        "spearman_rho": float(sr.statistic) if np.isfinite(sr.statistic) else np.nan,
        "spearman_pvalue": float(sr.pvalue) if np.isfinite(sr.pvalue) else np.nan,
        "macro_f1": float(macro),
        "balanced_accuracy": float(bal),
        "quadratic_weighted_kappa": float(qwk) if np.isfinite(qwk) else np.nan,
        "confusion_matrix": cm,
        "class_support": support,
        "warnings": warnings_seen,
    }


def metric_value(result: dict[str, object], metric: str) -> float:
    value = result.get(metric, np.nan)
    return float(value) if value is not None else float("nan")
