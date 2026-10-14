"""Deterministic leakage-group cluster bootstrap for fixed predictions."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aiz_rd.benchmark_metrics import METRICS, compute_metrics, metric_value


def cluster_bootstrap(
    frame: pd.DataFrame,
    *,
    difficulty_column: str,
    class_column: str,
    group_column: str = "leakage_group_id",
    repetitions: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    required = {difficulty_column, class_column, group_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"bootstrap frame missing columns: {sorted(missing)}")
    if repetitions != 1000:
        raise ValueError("Stage 10 requires exactly 1000 bootstrap repetitions")
    ordered = frame.sort_values([group_column, "reaction_hash"], kind="mergesort").reset_index(drop=True)
    groups = sorted(ordered[group_column].astype(str).unique().tolist())
    if not groups:
        raise ValueError("bootstrap frame has no groups")
    group_rows = {g: ordered.index[ordered[group_column].astype(str).eq(g)].to_numpy() for g in groups}
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for replicate in range(repetitions):
        sampled = rng.choice(np.asarray(groups, dtype=object), size=len(groups), replace=True)
        indices: list[int] = []
        for group in sampled.tolist():
            indices.extend(group_rows[str(group)].tolist())
        sample = ordered.iloc[indices]
        result = compute_metrics(sample[class_column].to_numpy(), sample[difficulty_column].to_numpy(), sample[f"{class_column}__pred"].to_numpy())
        rows.append({"replicate": replicate, **{metric: metric_value(result, metric) for metric in METRICS}})
    return pd.DataFrame(rows, columns=["replicate", *METRICS])


def paired_cluster_bootstrap(
    frame: pd.DataFrame,
    *,
    model_columns: dict[str, str],
    class_column: str = "expert_label",
    group_column: str = "leakage_group_id",
    repetitions: int = 1000,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return per-model and paired D-minus-baseline bootstrap replicates."""
    ordered = frame.sort_values([group_column, "reaction_hash"], kind="mergesort").reset_index(drop=True)
    groups = sorted(ordered[group_column].astype(str).unique().tolist())
    if repetitions != 1000:
        raise ValueError("Stage 10 requires exactly 1000 bootstrap repetitions")
    group_rows = {g: ordered.index[ordered[group_column].astype(str).eq(g)].to_numpy() for g in groups}
    rng = np.random.default_rng(seed)
    metric_rows: list[dict[str, object]] = []
    difference_rows: list[dict[str, object]] = []
    for replicate in range(repetitions):
        sampled = rng.choice(np.asarray(groups, dtype=object), size=len(groups), replace=True)
        indices: list[int] = []
        for group in sampled.tolist():
            indices.extend(group_rows[str(group)].tolist())
        sample = ordered.iloc[indices]
        metrics_by_model: dict[str, dict[str, object]] = {}
        for model, difficulty in model_columns.items():
            metric_input = sample[[class_column, difficulty]].copy()
            metric_input[f"{class_column}__pred"] = sample[f"{model}_class"]
            metrics_by_model[model] = compute_metrics(
                metric_input[class_column].to_numpy(),
                metric_input[difficulty].to_numpy(),
                metric_input[f"{class_column}__pred"].to_numpy(),
            )
            metric_rows.append({"replicate": replicate, "model": model, **{m: metric_value(metrics_by_model[model], m) for m in METRICS}})
        d_metrics = metrics_by_model["D"]
        for baseline in ["A", "B", "C", "E"]:
            b_metrics = metrics_by_model[baseline]
            difference_rows.append({"replicate": replicate, "comparison": f"D-{baseline}", **{m: metric_value(d_metrics, m) - metric_value(b_metrics, m) for m in METRICS}})
    return pd.DataFrame(metric_rows), pd.DataFrame(difference_rows)


def percentile_summary(values: pd.Series | np.ndarray, total: int = 1000) -> tuple[float, float, int, str | None]:
    values = np.asarray(values, dtype=np.float64)
    finite = values[np.isfinite(values)]
    warning = "CI_STABILITY_WARNING" if len(finite) < 900 else None
    if len(finite) == 0:
        return float("nan"), float("nan"), 0, warning
    return float(np.percentile(finite, 2.5)), float(np.percentile(finite, 97.5)), int(len(finite)), warning
