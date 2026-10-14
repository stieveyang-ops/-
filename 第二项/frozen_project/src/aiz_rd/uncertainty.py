"""Frozen analytical uncertainty and confidence functions for Stage 8."""
from __future__ import annotations

import numpy as np


def compute_uncertainty(p_feas, p_prec):
    """Compute U=[4*p_feas*(1-p_feas)+(1-p_prec)]/2 without imputation."""
    feas = np.asarray(p_feas, dtype=float)
    prec = np.asarray(p_prec, dtype=float)
    if feas.shape != prec.shape:
        raise ValueError("p_feas and p_prec shapes must match")
    if not np.isfinite(feas).all() or not np.isfinite(prec).all():
        raise ValueError("uncertainty inputs must be finite")
    if ((feas < 0) | (feas > 1) | (prec < 0) | (prec > 1)).any():
        raise ValueError("uncertainty inputs must be in [0,1]")
    result = (4.0 * feas * (1.0 - feas) + (1.0 - prec)) / 2.0
    if not np.isfinite(result).all() or ((result < 0) | (result > 1)).any():
        raise ValueError("computed uncertainty outside [0,1]")
    return result


def fit_confidence_thresholds(u_dev):
    values = np.asarray(u_dev, dtype=float)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise ValueError("u_dev must be a non-empty finite vector")
    if ((values < 0) | (values > 1)).any():
        raise ValueError("u_dev must be in [0,1]")
    q33 = float(np.quantile(values, 0.33, method="linear"))
    q67 = float(np.quantile(values, 0.67, method="linear"))
    if q33 > q67:
        raise ValueError("q33 must not exceed q67")
    return q33, q67


def assign_confidence(u, q33, q67):
    value = np.asarray(u, dtype=float)
    if not np.isfinite(value).all() or ((value < 0) | (value > 1)).any():
        raise ValueError("u must be finite and in [0,1]")
    if not (np.isfinite(q33) and np.isfinite(q67) and 0 <= q33 <= q67 <= 1):
        raise ValueError("invalid confidence thresholds")
    return np.where(value <= q33, "High", np.where(value <= q67, "Medium", "Low"))
