"""Fixed Stage 6 development baseline.

This module deliberately contains no fitting, calibration, clipping, or
imputation.  The score is an engineering smoke-test baseline only and is not
the final scientific model.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


WEIGHT_FEAS = 0.45
WEIGHT_PREC = 0.40
WEIGHT_SC = 0.15
BASELINE_LABEL = "DEVELOPMENT BASELINE ONLY - NOT FINAL MODEL"


class DevelopmentBaselineError(ValueError):
    """Raised when baseline inputs violate the frozen mathematical contract."""


def _validate_component(name: str, value: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DevelopmentBaselineError(f"{name} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise DevelopmentBaselineError(f"{name} is non-finite: {result!r}")
    if not 0.0 <= result <= 1.0:
        raise DevelopmentBaselineError(f"{name} outside [0,1]: {result!r}")
    return result


def difficulty_dev(d_feas: float, d_prec: float, d_sc: float) -> float:
    """Compute the frozen 45/40/15 development baseline for one row."""

    if abs(WEIGHT_FEAS + WEIGHT_PREC + WEIGHT_SC - 1.0) >= 1e-15:
        raise DevelopmentBaselineError("development baseline weights do not sum to 1")
    f = _validate_component("d_feas", d_feas)
    p = _validate_component("d_prec", d_prec)
    s = _validate_component("d_sc", d_sc)
    result = 100.0 * (WEIGHT_FEAS * f + WEIGHT_PREC * p + WEIGHT_SC * s)
    if not math.isfinite(result) or not 0.0 <= result <= 100.0:
        raise DevelopmentBaselineError(f"difficulty_dev outside [0,100]: {result!r}")
    return float(result)


def add_dev_baseline(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with ``difficulty_dev`` calculated without repair."""

    required = ["d_feas", "d_prec", "d_sc"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise DevelopmentBaselineError(f"missing baseline columns: {missing}")
    values = frame[required].to_numpy(dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
        raise DevelopmentBaselineError("baseline inputs contain NaN/Inf")
    if np.any(values < 0.0) or np.any(values > 1.0):
        raise DevelopmentBaselineError("baseline inputs outside [0,1]")
    if abs(WEIGHT_FEAS + WEIGHT_PREC + WEIGHT_SC - 1.0) >= 1e-15:
        raise DevelopmentBaselineError("development baseline weights do not sum to 1")
    result = 100.0 * (
        WEIGHT_FEAS * values[:, 0]
        + WEIGHT_PREC * values[:, 1]
        + WEIGHT_SC * values[:, 2]
    )
    if not np.isfinite(result).all() or np.any(result < 0.0) or np.any(result > 100.0):
        raise DevelopmentBaselineError("difficulty_dev outside [0,100]")
    out = frame.copy()
    out["difficulty_dev"] = result.astype(np.float64)
    return out


def run_boundary_and_monotonicity_tests() -> dict[str, object]:
    """Run deterministic analytic tests required by the Stage 6 contract."""

    if abs(WEIGHT_FEAS + WEIGHT_PREC + WEIGHT_SC - 1.0) >= 1e-15:
        raise DevelopmentBaselineError("weight sum test failed")
    boundaries = {
        "all_easy": (0.0, 0.0, 0.0, 0.0),
        "all_hard": (1.0, 1.0, 1.0, 100.0),
        "feas_only": (1.0, 0.0, 0.0, 45.0),
        "precedent_only": (0.0, 1.0, 0.0, 40.0),
        "sc_only": (0.0, 0.0, 1.0, 15.0),
    }
    boundary_results = {}
    for name, (f, p, s, expected) in boundaries.items():
        actual = difficulty_dev(f, p, s)
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12):
            raise DevelopmentBaselineError(f"boundary test failed: {name}: {actual} != {expected}")
        boundary_results[name] = actual

    base = difficulty_dev(0.2, 0.2, 0.2)
    p_feas_drop = difficulty_dev(0.3, 0.2, 0.2) - base
    p_prec_drop = difficulty_dev(0.2, 0.3, 0.2) - base
    d_sc_rise = difficulty_dev(0.2, 0.2, 0.3) - base
    # A 0.1 rise in D_F/D_P/D_SC is respectively 4.5/4.0/1.5 points.
    expected_deltas = {"p_feas_drop": 4.5, "p_prec_drop": 4.0, "d_sc_rise": 1.5}
    actual_deltas = {
        "p_feas_drop": p_feas_drop,
        "p_prec_drop": p_prec_drop,
        "d_sc_rise": d_sc_rise,
    }
    for name, expected in expected_deltas.items():
        if not math.isclose(actual_deltas[name], expected, rel_tol=0.0, abs_tol=1e-12):
            raise DevelopmentBaselineError(
                f"monotonicity test failed: {name}: {actual_deltas[name]} != {expected}"
            )
    # P_feas/P_prec decrease means D_F/D_P increase; the analytic derivative
    # of D_dev with respect to the probabilities is -45 and -40.
    return {
        "weight_sum": WEIGHT_FEAS + WEIGHT_PREC + WEIGHT_SC,
        "boundaries": boundary_results,
        "monotonicity_deltas": actual_deltas,
        "all_pass": True,
    }
