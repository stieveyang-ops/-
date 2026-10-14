"""Strict Stage 6 feature-pipeline assembly and validation helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from aiz_rd.dev_baseline import BASELINE_LABEL, add_dev_baseline, run_boundary_and_monotonicity_tests


KEY_COLUMNS = ["target_id", "route_id", "step_id", "reaction_hash"]
FINAL_COLUMNS = [
    "target_id",
    "route_id",
    "step_id",
    "reaction_hash",
    "reaction_smiles",
    "product_smiles",
    "precursor_smiles",
    "p_feas",
    "d_feas",
    "s_max",
    "n_analog",
    "p_prec",
    "d_prec",
    "sc_product",
    "sc_precursor_max",
    "delta_sc",
    "d_sc",
    "difficulty_dev",
]
FEATURE_COLUMNS = [column for column in FINAL_COLUMNS if column != "difficulty_dev"]
PROBABILITY_COLUMNS = ["p_feas", "d_feas", "s_max", "p_prec", "d_prec", "d_sc"]
FINITE_COLUMNS = PROBABILITY_COLUMNS + ["sc_product", "sc_precursor_max", "delta_sc"]


class Stage6ValidationError(RuntimeError):
    """A mandatory Stage 6 identity, provenance, schema, or math check failed."""


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _key_tuple(row: Iterable[object]) -> tuple[object, ...]:
    return tuple(value.item() if isinstance(value, np.generic) else value for value in row)


def _key_list(frame: pd.DataFrame) -> list[tuple[object, ...]]:
    return [_key_tuple(row) for row in frame[KEY_COLUMNS].itertuples(index=False, name=None)]


def _key_examples(keys: Iterable[tuple[object, ...]], limit: int = 5) -> list[list[object]]:
    return [list(key) for key in list(keys)[:limit]]


def validate_key_table(frame: pd.DataFrame, name: str, *, expected_columns: Iterable[str] = KEY_COLUMNS) -> dict[str, int]:
    missing = [column for column in expected_columns if column not in frame.columns]
    if missing:
        raise Stage6ValidationError(f"{name}: missing required columns {missing}")
    null_mask = frame[list(expected_columns)].isna().any(axis=1)
    blank_mask = pd.Series(False, index=frame.index)
    for column in expected_columns:
        if pd.api.types.is_object_dtype(frame[column]) or pd.api.types.is_string_dtype(frame[column]):
            blank_mask |= frame[column].astype("string").str.strip().eq("").fillna(False)
    if bool((null_mask | blank_mask).any()):
        bad = frame.loc[null_mask | blank_mask, list(expected_columns)].head(5).to_dict("records")
        raise Stage6ValidationError(f"{name}: missing/blank key cells; examples={bad}")
    duplicate_count = int(frame.duplicated(list(expected_columns), keep=False).sum())
    if duplicate_count:
        duplicates = frame.loc[frame.duplicated(list(expected_columns), keep=False), list(expected_columns)].head(5).to_dict("records")
        raise Stage6ValidationError(f"{name}: duplicate composite keys={duplicate_count}; examples={duplicates}")
    return {"rows": int(len(frame)), "duplicate_key_rows": duplicate_count, "missing_key_rows": 0}


def verify_file_hash(path: str | Path, expected: str, label: str) -> str:
    actual = sha256(path)
    if actual != str(expected).upper():
        raise Stage6ValidationError(f"{label}: SHA256 mismatch expected={expected} actual={actual} path={path}")
    return actual


def _strict_align(base: pd.DataFrame, feature: pd.DataFrame, name: str) -> pd.DataFrame:
    validate_key_table(base, "Stage 2 base")
    validate_key_table(feature, name)
    base_keys = _key_list(base)
    feature_keys = _key_list(feature)
    base_set = set(base_keys)
    feature_set = set(feature_keys)
    missing = base_set - feature_set
    extra = feature_set - base_set
    if missing or extra:
        raise Stage6ValidationError(
            f"{name}: exact key-set mismatch missing={len(missing)} extra={len(extra)} "
            f"missing_examples={_key_examples(missing)} extra_examples={_key_examples(extra)}"
        )
    positions = {key: index for index, key in enumerate(feature_keys)}
    aligned = feature.iloc[[positions[key] for key in base_keys]].reset_index(drop=True)
    if _key_list(aligned) != base_keys:
        raise Stage6ValidationError(f"{name}: deterministic key alignment failed")
    return aligned


def _assert_equal_strings(left: pd.Series, right: pd.Series, label: str) -> None:
    mismatch = left.astype("string").fillna("<NA>") != right.astype("string").fillna("<NA>")
    if bool(mismatch.any()):
        indices = mismatch[mismatch].index[:5].tolist()
        raise Stage6ValidationError(f"{label}: conflicting values at rows {indices}")


def strict_merge_features(
    base: pd.DataFrame,
    feasibility: pd.DataFrame,
    sc_raw: pd.DataFrame,
    precedent: pd.DataFrame,
    sc_normalized: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Strictly attach frozen feature tables in Stage 2 base order."""

    validate_key_table(base, "Stage 2 base")
    aligned_feas = _strict_align(base, feasibility, "Stage 3 feasibility")
    aligned_sc = _strict_align(base, sc_raw, "Stage 3 SC raw")
    aligned_prec = _strict_align(base, precedent, "Stage 5 precedent")
    aligned_norm = _strict_align(base, sc_normalized, "Stage 5 D_SC")

    for name, table in [("Stage 3 feasibility", aligned_feas), ("Stage 3 SC raw", aligned_sc), ("Stage 5 precedent", aligned_prec), ("Stage 5 D_SC", aligned_norm)]:
        if len(table) != len(base):
            raise Stage6ValidationError(f"{name}: row count {len(table)} != base {len(base)}")

    for name, table in [("Stage 3 SC raw", aligned_sc), ("Stage 5 precedent", aligned_prec), ("Stage 5 D_SC", aligned_norm)]:
        if "reaction_smiles" in table.columns:
            _assert_equal_strings(table["reaction_smiles"], base["reaction_smiles"], f"{name} reaction_smiles")
    if "product_smiles" in aligned_sc.columns:
        _assert_equal_strings(aligned_sc["product_smiles"], base["product_smiles"], "Stage 3 SC raw product_smiles")
    if "reaction_smiles" in aligned_norm.columns:
        _assert_equal_strings(aligned_norm["reaction_smiles"], base["reaction_smiles"], "Stage 5 D_SC reaction_smiles")
    for column in ["sc_product", "sc_precursor_max", "delta_sc"]:
        if column in aligned_norm.columns:
            if not np.allclose(aligned_norm[column].to_numpy(float), aligned_sc[column].to_numpy(float), atol=1e-12, rtol=0.0):
                raise Stage6ValidationError(f"Stage 5 D_SC {column} conflicts with Stage 3 SC raw")

    out = base[["target_id", "route_id", "step_id", "reaction_hash", "reaction_smiles", "product_smiles", "precursor_smiles"]].copy()
    out["p_feas"] = aligned_feas["p_feas"].to_numpy()
    out["d_feas"] = aligned_feas["d_feas"].to_numpy()
    for column in ["s_max", "n_analog", "p_prec", "d_prec"]:
        out[column] = aligned_prec[column].to_numpy()
    for column in ["sc_product", "sc_precursor_max", "delta_sc"]:
        out[column] = aligned_sc[column].to_numpy()
    out["d_sc"] = aligned_norm["d_sc"].to_numpy()
    if any(column.endswith(("_x", "_y")) for column in out.columns):
        raise Stage6ValidationError("merge produced ambiguous _x/_y columns")
    if out.columns.tolist() != FEATURE_COLUMNS:
        raise Stage6ValidationError(f"unexpected pre-baseline schema: {out.columns.tolist()}")
    return out, {
        "base_rows": int(len(base)),
        "feasibility_rows_matched": int(len(aligned_feas)),
        "sc_raw_rows_matched": int(len(aligned_sc)),
        "precedent_rows_matched": int(len(aligned_prec)),
        "d_sc_rows_matched": int(len(aligned_norm)),
        "missing_keys": 0,
        "extra_keys": 0,
        "duplicate_keys": 0,
    }


def validate_feature_values(
    frame: pd.DataFrame,
    *,
    stage5_manifest: Mapping[str, object] | None = None,
    require_difficulty: bool = False,
) -> dict[str, object]:
    """Fail-fast validation of all Stage 6 feature invariants."""

    required = FINAL_COLUMNS if require_difficulty else FEATURE_COLUMNS
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise Stage6ValidationError(f"feature table missing required columns: {missing}")
    validate_key_table(frame, "reaction_features")
    if frame.columns.tolist() != required:
        raise Stage6ValidationError(f"feature schema/order mismatch: {frame.columns.tolist()} expected={required}")
    finite_counts = {}
    for column in FINITE_COLUMNS + (["difficulty_dev"] if require_difficulty else []):
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=np.float64)
        finite_counts[column] = int(np.isfinite(values).sum())
        if len(values) != finite_counts[column]:
            raise Stage6ValidationError(f"{column}: NaN/Inf present")
    for column in PROBABILITY_COLUMNS:
        values = frame[column].to_numpy(dtype=np.float64)
        if np.any(values < 0.0) or np.any(values > 1.0):
            raise Stage6ValidationError(f"{column}: value outside [0,1]")
    n_analog = pd.to_numeric(frame["n_analog"], errors="coerce").to_numpy(dtype=np.float64)
    if np.any(~np.isfinite(n_analog)) or np.any(n_analog < 0.0) or np.any(n_analog != np.floor(n_analog)):
        raise Stage6ValidationError("n_analog: non-finite, negative, or non-integer value")
    if not np.allclose(frame["d_feas"].to_numpy(float), 1.0 - frame["p_feas"].to_numpy(float), atol=1e-7, rtol=0.0):
        raise Stage6ValidationError("d_feas != 1 - p_feas")
    if not np.allclose(frame["d_prec"].to_numpy(float), 1.0 - frame["p_prec"].to_numpy(float), atol=1e-12, rtol=0.0):
        raise Stage6ValidationError("d_prec != 1 - p_prec")
    if not np.allclose(frame["delta_sc"].to_numpy(float), frame["sc_product"].to_numpy(float) - frame["sc_precursor_max"].to_numpy(float), atol=1e-12, rtol=0.0):
        raise Stage6ValidationError("delta_sc != sc_product - sc_precursor_max")
    if stage5_manifest is not None:
        if float(stage5_manifest.get("tau")) != 0.8 or float(stage5_manifest.get("n0")) != 10.0 or stage5_manifest.get("precedent_mode") != "deployment":
            raise Stage6ValidationError("Stage 5 precedent parameters drifted from tau=0.80, N0=10, deployment")
    summary: dict[str, object] = {
        "row_count": int(len(frame)),
        "finite_counts": finite_counts,
        "nan_count": int(frame.isna().sum().sum()),
        "inf_count": 0,
        "range_checks": {column: True for column in PROBABILITY_COLUMNS},
        "formula_checks": {"d_feas": True, "d_prec": True, "delta_sc": True},
        "n_analog_integer_nonnegative": True,
    }
    if require_difficulty:
        values = frame["difficulty_dev"].to_numpy(dtype=np.float64)
        if np.any(values < 0.0) or np.any(values > 100.0):
            raise Stage6ValidationError("difficulty_dev outside [0,100]")
        expected = 100.0 * (0.45 * frame["d_feas"].to_numpy(float) + 0.40 * frame["d_prec"].to_numpy(float) + 0.15 * frame["d_sc"].to_numpy(float))
        if not np.allclose(values, expected, atol=1e-12, rtol=0.0):
            raise Stage6ValidationError("difficulty_dev formula mismatch")
        summary["formula_checks"]["difficulty_dev"] = True
        summary["difficulty_dev"] = {
            "min": float(np.min(values)),
            "median": float(np.median(values)),
            "max": float(np.max(values)),
            "q25": float(np.quantile(values, 0.25)),
            "q75": float(np.quantile(values, 0.75)),
        }
    return summary


def build_features(
    base: pd.DataFrame,
    feasibility: pd.DataFrame,
    sc_raw: pd.DataFrame,
    precedent: pd.DataFrame,
    sc_normalized: pd.DataFrame,
    *,
    stage5_manifest: Mapping[str, object] | None = None,
    include_difficulty: bool = True,
) -> tuple[pd.DataFrame, dict[str, object]]:
    features, merge_summary = strict_merge_features(base, feasibility, sc_raw, precedent, sc_normalized)
    pre_summary = validate_feature_values(features, stage5_manifest=stage5_manifest, require_difficulty=False)
    if include_difficulty:
        features = add_dev_baseline(features)
        final_summary = validate_feature_values(features, stage5_manifest=stage5_manifest, require_difficulty=True)
        features = features[FINAL_COLUMNS]
    else:
        final_summary = pre_summary
    return features, {"merge": merge_summary, "validation": final_summary, "pre_baseline_validation": pre_summary}


def atomic_write_parquet(frame: pd.DataFrame, destination: str | Path) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        frame.to_parquet(temporary_path, index=False)
        check = pd.read_parquet(temporary_path)
        if check.columns.tolist() != frame.columns.tolist() or len(check) != len(frame):
            raise Stage6ValidationError("temporary Parquet round-trip schema/row mismatch")
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def package_versions() -> dict[str, str | None]:
    from importlib.metadata import version

    names = ["aizynthfinder", "rdkit", "numpy", "pandas", "scikit-learn", "rxnfp", "ord-schema", "pyarrow"]
    result: dict[str, str | None] = {}
    for name in names:
        try:
            result[name] = version(name)
        except Exception:
            result[name] = None
    return result


def git_identity(root: Path) -> tuple[str | None, str]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
        return commit or None, "resolved from local Git worktree"
    except Exception:
        return None, "Project directory is not a Git worktree"


def json_dump_atomic(path: str | Path, payload: Mapping[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        temporary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
