"""Stage 7 blind expert-annotation infrastructure.

This module contains deterministic sampling, leakage audits, strict expert
file validation, and agreement calculations.  It never generates a chemistry
difficulty label.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd


KEY_COLUMNS = ["target_id", "route_id", "step_id", "reaction_hash"]
HIDDEN_COLUMNS = KEY_COLUMNS + ["reaction_smiles", "product_smiles", "precursor_smiles"]
CORE_FEATURE_COLUMNS = ["p_feas", "d_feas", "p_prec", "d_prec", "delta_sc", "d_sc"]
VISIBLE_COLUMNS = ["reaction_id", "reaction_smiles", "reactants", "product", "expert_label"]
LABEL_VALUES = {"0", "1", "2", "3"}
REACTION_ID_PATTERN = re.compile(r"^RXNANN_[0-9A-F]{16}$")
# These tokens are deliberately field/model terms, not generic chemistry
# words.  They are checked in headers and cell content of expert files.
FORBIDDEN_SUBSTRINGS = [
    "target_id", "route_id", "step_id", "reaction_hash", "p_feas", "d_feas",
    "s_max", "n_analog", "p_prec", "d_prec", "sc_product", "sc_precursor",
    "delta_sc", "d_sc", "difficulty_dev", "aizynthfinder", "state_score",
    "route_rank", "nearest_reference", "reference_database", "solved", "unsolved",
]

# Frozen project salt.  It is never written to expert-visible files; only its
# hash is recorded in the manifest.  The opaque ID is not derived from any
# target/route/step text in a readable way.
REACTION_ID_SALT = "stage7-frozen-reaction-id-salt-v1::aizynth-reaction-difficulty"


class AnnotationValidationError(RuntimeError):
    """A mandatory Stage 7 annotation or blinding check failed."""


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def atomic_write_text(path: str | Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_text(content, encoding="utf-8", newline="")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_write_csv(frame: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        frame.to_csv(tmp_path, index=False, encoding="utf-8-sig", lineterminator="\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_write_parquet(frame: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        frame.to_parquet(tmp_path, index=False)
        check = pd.read_parquet(tmp_path)
        if check.columns.tolist() != frame.columns.tolist() or len(check) != len(frame):
            raise AnnotationValidationError("atomic Parquet round-trip schema/row mismatch")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_write_json(payload: Mapping[str, object], path: str | Path) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


def opaque_reaction_id(reaction_hash: str) -> str:
    if not isinstance(reaction_hash, str) or not reaction_hash.strip():
        raise AnnotationValidationError("reaction_hash is empty while creating opaque ID")
    digest = hashlib.sha256((reaction_hash + "|" + REACTION_ID_SALT).encode("utf-8")).hexdigest().upper()
    return "RXNANN_" + digest[:16]


def validate_stage6_features(features: pd.DataFrame, steps: pd.DataFrame) -> None:
    required_features = HIDDEN_COLUMNS + CORE_FEATURE_COLUMNS + ["difficulty_dev"]
    missing = [column for column in required_features if column not in features.columns]
    if missing:
        raise AnnotationValidationError(f"Stage 6 feature table missing columns: {missing}")
    missing_steps = [column for column in KEY_COLUMNS + ["reaction_smiles", "product_smiles", "precursor_smiles"] if column not in steps.columns]
    if missing_steps:
        raise AnnotationValidationError(f"Stage 2 table missing columns: {missing_steps}")
    if features.empty:
        raise AnnotationValidationError("Stage 6 feature table is empty")
    if features[KEY_COLUMNS].isna().any().any():
        raise AnnotationValidationError("Stage 6 feature table contains missing identity fields")
    if features[KEY_COLUMNS].duplicated().any():
        raise AnnotationValidationError("Stage 6 feature table has duplicate composite keys")
    if features["reaction_hash"].isna().any() or features["reaction_hash"].duplicated().any():
        # Duplicate chemistry is expected across routes, so only the first
        # check is fatal here; hash duplication is handled by deduplication.
        if features["reaction_hash"].isna().any():
            raise AnnotationValidationError("Stage 6 feature table has missing reaction_hash")
    for column in CORE_FEATURE_COLUMNS + ["difficulty_dev"]:
        values = pd.to_numeric(features[column], errors="coerce").to_numpy(dtype=np.float64)
        if not np.isfinite(values).all():
            raise AnnotationValidationError(f"Stage 6 feature column {column} contains NaN/Inf")
    for column in ["p_feas", "d_feas", "p_prec", "d_prec", "d_sc"]:
        values = features[column].to_numpy(dtype=np.float64)
        if np.any(values < 0.0) or np.any(values > 1.0):
            raise AnnotationValidationError(f"Stage 6 feature column {column} is outside [0,1]")
    if not np.allclose(features["d_feas"].to_numpy(float), 1.0 - features["p_feas"].to_numpy(float), atol=1e-7, rtol=0.0):
        raise AnnotationValidationError("Stage 6 d_feas identity failed")
    if not np.allclose(features["d_prec"].to_numpy(float), 1.0 - features["p_prec"].to_numpy(float), atol=1e-12, rtol=0.0):
        raise AnnotationValidationError("Stage 6 d_prec identity failed")
    if not np.allclose(features["difficulty_dev"].to_numpy(float), 100.0 * (0.45 * features.d_feas + 0.40 * features.d_prec + 0.15 * features.d_sc), atol=1e-12, rtol=0.0):
        raise AnnotationValidationError("Stage 6 difficulty_dev formula failed")
    if not np.all(features["difficulty_dev"].between(0.0, 100.0)):
        raise AnnotationValidationError("Stage 6 difficulty_dev outside [0,100]")


def deduplicate_candidates(features: pd.DataFrame) -> pd.DataFrame:
    """Select one deterministic occurrence per reaction_hash after consistency checks."""

    sort_columns = ["target_id", "route_id", "step_id"]
    ordered = features.sort_values(sort_columns, kind="mergesort").reset_index(drop=True)
    records: list[dict[str, object]] = []
    for reaction_hash, group in ordered.groupby("reaction_hash", sort=True, dropna=False):
        if not isinstance(reaction_hash, str) or not reaction_hash:
            raise AnnotationValidationError("empty reaction_hash in deduplication group")
        for column in ["reaction_smiles", "product_smiles", "precursor_smiles"]:
            vals = group[column].astype("string").fillna("<NA>").unique().tolist()
            if len(vals) != 1:
                raise AnnotationValidationError(f"inconsistent {column} for reaction_hash={reaction_hash}: {vals[:5]}")
        for column in CORE_FEATURE_COLUMNS:
            values = pd.to_numeric(group[column], errors="coerce").to_numpy(dtype=np.float64)
            if not np.isfinite(values).all() or not np.allclose(values, values[0], atol=1e-12, rtol=0.0):
                raise AnnotationValidationError(f"inconsistent {column} for reaction_hash={reaction_hash}")
        representative = group.iloc[0].to_dict()
        representative["source_occurrence_count"] = int(len(group))
        records.append(representative)
    result = pd.DataFrame(records)
    if result.empty:
        raise AnnotationValidationError("no unique candidate reactions after deduplication")
    if result["reaction_hash"].duplicated().any():
        raise AnnotationValidationError("deduplicated candidate reaction_hash is not unique")
    return result.reset_index(drop=True)


def _bin_feature(values: pd.Series) -> tuple[pd.Series, dict[str, object]]:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=np.float64)
    if not np.isfinite(numeric).all():
        raise AnnotationValidationError("non-finite value encountered during tertile binning")
    unique = np.unique(numeric)
    q1, q2 = np.quantile(numeric, [1 / 3, 2 / 3]).tolist()
    if len(unique) == 1:
        labels = pd.Series(["only"] * len(numeric), index=values.index, dtype="string")
        effective_edges = [float(unique[0])]
        n_bins = 1
    else:
        thresholds: list[float] = []
        for threshold in [float(q1), float(q2)]:
            if threshold < float(unique[-1]) and threshold not in thresholds:
                thresholds.append(threshold)
        thresholds.sort()
        codes = np.digitize(numeric, thresholds, right=True)
        label_names = ["low", "middle", "high"][: len(thresholds) + 1]
        labels = pd.Series([label_names[int(code)] for code in codes], index=values.index, dtype="string")
        effective_edges = [-math.inf] + thresholds + [math.inf]
        n_bins = len(label_names)
        # Remove empty labels from the declared effective bin count only when
        # ties make a nominal bin empty; no jitter or synthetic value is used.
        present = set(labels.tolist())
        label_names = [name for name in label_names if name in present]
        n_bins = len(label_names)
    return labels, {
        "quantile_tertiles": {"q1": float(q1), "q2": float(q2)},
        "effective_edges": effective_edges,
        "n_effective_bins": n_bins,
        "unique_value_count": int(len(unique)),
    }


def stratified_sample(candidates: pd.DataFrame, target_n: int, seed: int) -> tuple[pd.DataFrame, dict[str, object]]:
    if target_n <= 0:
        raise AnnotationValidationError("target_n must be positive")
    if len(candidates) < target_n:
        raise AnnotationValidationError(f"candidate pool {len(candidates)} is smaller than requested target_n {target_n}")
    work = candidates.copy()
    bin_info: dict[str, object] = {}
    for column, short in [("p_feas", "feas"), ("p_prec", "prec"), ("d_sc", "dsc")]:
        labels, info = _bin_feature(work[column])
        work[f"_{short}_bin"] = labels
        bin_info[short] = info
    work["_stratum"] = work["_feas_bin"] + "x" + work["_prec_bin"] + "x" + work["_dsc_bin"]
    strata = {}
    randomized: dict[str, pd.DataFrame] = {}
    for stratum, group in work.groupby("_stratum", sort=True):
        group = group.sort_values("reaction_hash", kind="mergesort")
        randomized[stratum] = group.sample(frac=1.0, random_state=seed).reset_index(drop=True)
        strata[stratum] = int(len(group))
    if target_n < len(strata):
        # The contract asks for broad coverage; with target_n >= 200 this is
        # normally impossible, but fail explicitly rather than under-cover.
        raise AnnotationValidationError(f"target_n={target_n} smaller than non-empty stratum count={len(strata)}")
    selected: list[pd.Series] = []
    positions = {name: 0 for name in randomized}
    counts = {name: 0 for name in randomized}
    # Base quota: one from every non-empty stratum.
    for name in sorted(randomized):
        selected.append(randomized[name].iloc[0])
        positions[name] = 1
        counts[name] = 1
    while len(selected) < target_n:
        available = [name for name in sorted(randomized) if positions[name] < len(randomized[name])]
        if not available:
            raise AnnotationValidationError("stratified sampler exhausted candidates before target_n")
        name = min(available, key=lambda item: (counts[item], item))
        selected.append(randomized[name].iloc[positions[name]])
        positions[name] += 1
        counts[name] += 1
    sampled = pd.DataFrame(selected).reset_index(drop=True)
    sampled = sampled.sort_values("reaction_hash", kind="mergesort").reset_index(drop=True)
    sample_counts = {name: int(counts[name]) for name in sorted(counts)}
    # Internal bin columns are not part of hidden key or expert files.
    sampled = sampled.drop(columns=["_feas_bin", "_prec_bin", "_dsc_bin", "_stratum"])
    return sampled, {
        "bin_edges": bin_info,
        "stratum_population_counts": strata,
        "stratum_sample_counts": sample_counts,
        "non_empty_strata": int(len(strata)),
    }


def make_annotation_tables(sampled: pd.DataFrame, n_experts: int, base_seed: int) -> dict[str, object]:
    if n_experts < 2:
        raise AnnotationValidationError("at least two independent experts are required")
    sampled = sampled.copy()
    sampled["reaction_id"] = sampled["reaction_hash"].map(opaque_reaction_id)
    if sampled["reaction_id"].duplicated().any() or not sampled["reaction_id"].map(lambda x: bool(REACTION_ID_PATTERN.fullmatch(str(x)))).all():
        raise AnnotationValidationError("opaque reaction_id generation failed")
    key_columns = ["reaction_id", "reaction_hash", "target_id", "route_id", "step_id", "reaction_smiles", "product_smiles", "precursor_smiles", "source_occurrence_count"]
    key = sampled[key_columns].copy()
    key["source_occurrence_count"] = key["source_occurrence_count"].astype("int64")
    master = pd.DataFrame({
        "reaction_id": sampled["reaction_id"].astype(str),
        "reaction_smiles": sampled["reaction_smiles"].astype(str),
        "reactants": sampled["precursor_smiles"].astype(str),
        "product": sampled["product_smiles"].astype(str),
        "expert_label": [""] * len(sampled),
    })
    experts: dict[str, pd.DataFrame] = {}
    seeds: dict[str, int] = {}
    for idx in range(n_experts):
        expert_id = f"E{idx + 1:02d}"
        shuffle_seed = base_seed * 100 + idx + 1
        seeds[expert_id] = shuffle_seed
        experts[expert_id] = master.sample(frac=1.0, random_state=shuffle_seed).reset_index(drop=True)
    return {"key": key, "master": master, "experts": experts, "shuffle_seeds": seeds}


def audit_blinded_frame(frame: pd.DataFrame, *, expected_ids: set[str] | None = None) -> dict[str, object]:
    if frame.columns.tolist() != VISIBLE_COLUMNS:
        raise AnnotationValidationError(f"expert-visible columns {frame.columns.tolist()} != {VISIBLE_COLUMNS}")
    if frame["expert_label"].fillna("").astype(str).str.strip().ne("").any():
        raise AnnotationValidationError("expert_label is not blank in initial blind file")
    if frame["reaction_id"].duplicated().any() or not frame["reaction_id"].map(lambda x: bool(REACTION_ID_PATTERN.fullmatch(str(x)))).all():
        raise AnnotationValidationError("expert-visible reaction_id is not opaque/unique")
    if expected_ids is not None and set(frame["reaction_id"].astype(str)) != set(expected_ids):
        raise AnnotationValidationError("expert-visible reaction_id set mismatch")
    scan_columns = "|".join(str(x) for x in frame.columns).lower()
    scan_values = "|".join(frame.astype(str).fillna("").to_numpy().reshape(-1)).lower()
    hits = sorted({token for token in FORBIDDEN_SUBSTRINGS if token in scan_columns or token in scan_values})
    if hits:
        raise AnnotationValidationError(f"forbidden blinding tokens detected: {hits}")
    return {"columns": frame.columns.tolist(), "rows": int(len(frame)), "forbidden_hits": [], "labels_blank": True}


def build_adjudication_required(long: pd.DataFrame, master: pd.DataFrame, expert_ids: list[str]) -> pd.DataFrame:
    pivot = long.pivot(index="reaction_id", columns="expert_id", values="expert_label")
    for expert_id in expert_ids:
        if expert_id not in pivot.columns:
            raise AnnotationValidationError(f"missing expert {expert_id} in long annotations")
    pivot = pivot[expert_ids]
    needs = []
    for reaction_id, row in pivot.iterrows():
        labels = [row[expert_id] for expert_id in expert_ids]
        non_abstain = [label for label in labels if pd.notna(label) and int(label) != 3]
        disagreement = len(set(non_abstain)) > 1
        abstain = any(pd.isna(label) or int(label) == 3 for label in labels)
        if disagreement or abstain:
            needs.append(reaction_id)
    base = master.set_index("reaction_id").loc[needs].reset_index()
    out = base[["reaction_id", "reaction_smiles", "reactants", "product"]].copy()
    for expert_id in expert_ids:
        out[f"label_{expert_id}"] = [pivot.loc[rid, expert_id] for rid in out["reaction_id"]]
    out["adjudicated_label"] = ""
    return out


def _parse_label(value: object, *, allow_blank: bool = False) -> int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)) or str(value) == "":
        if allow_blank:
            return None
        raise AnnotationValidationError("expert_label is blank")
    text = str(value)
    if text not in LABEL_VALUES:
        raise AnnotationValidationError(f"expert_label must be literal integer 0/1/2/3, got {value!r}")
    return int(text)


def validate_expert_file(path: Path, master: pd.DataFrame, expert_id: str) -> tuple[pd.DataFrame, str]:
    if not path.is_file():
        raise AnnotationValidationError(f"missing expert file: {path}")
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    audit_blinded_frame(raw.drop(columns=["expert_label"]).assign(expert_label=""), expected_ids=set(master.reaction_id)) if set(raw.columns) == set(VISIBLE_COLUMNS) else None
    if raw.columns.tolist() != VISIBLE_COLUMNS:
        raise AnnotationValidationError(f"{expert_id}: columns must exactly equal {VISIBLE_COLUMNS}")
    if raw["reaction_id"].duplicated().any() or set(raw.reaction_id) != set(master.reaction_id):
        raise AnnotationValidationError(f"{expert_id}: reaction_id set is not exactly equal to master")
    reference = master.set_index("reaction_id")
    for column in ["reaction_smiles", "reactants", "product"]:
        for reaction_id, value in raw.set_index("reaction_id")[column].items():
            if str(value) != str(reference.loc[reaction_id, column]):
                raise AnnotationValidationError(f"{expert_id}: modified {column} for {reaction_id}")
    labels = [_parse_label(value) for value in raw["expert_label"].tolist()]
    result = raw.copy()
    result["expert_label"] = labels
    return result, sha256(path)


def ordinal_krippendorff_alpha(matrix: list[list[int | None]]) -> float | None:
    """Ordinal Krippendorff alpha with label 3/None treated as missing."""

    categories = [0, 1, 2]
    coincidence = np.zeros((3, 3), dtype=float)
    total_units = 0
    for ratings in matrix:
        observed = [int(x) for x in ratings if x is not None and int(x) in categories]
        if len(observed) < 2:
            continue
        total_units += 1
        counts = np.array([observed.count(category) for category in categories], dtype=float)
        m = float(len(observed))
        for i, count_i in enumerate(counts):
            for j, count_j in enumerate(counts):
                coincidence[i, j] += count_i * (count_j - (1.0 if i == j else 0.0)) / (m - 1.0)
    if coincidence.sum() == 0.0:
        return None
    n = coincidence.sum(axis=1)
    n_total = n.sum()
    observed_disagreement = 0.0
    expected_disagreement = 0.0
    for i in range(3):
        for j in range(3):
            distance = float((i - j) ** 2)
            observed_disagreement += coincidence[i, j] * distance
            expected_disagreement += (n[i] * (n[j] - (1.0 if i == j else 0.0)) / (n_total - 1.0)) * distance
    if expected_disagreement == 0.0:
        return 1.0 if observed_disagreement == 0.0 else 0.0
    return float(1.0 - observed_disagreement / expected_disagreement)


def agreement_report(long: pd.DataFrame) -> dict[str, object]:
    required = ["reaction_id", "expert_id", "expert_label", "is_abstain", "source_file_sha256", "annotation_file_row_number"]
    missing = [column for column in required if column not in long.columns]
    if missing:
        raise AnnotationValidationError(f"long annotation table missing columns: {missing}")
    expert_ids = sorted(long["expert_id"].astype(str).unique())
    if len(expert_ids) < 2:
        raise AnnotationValidationError("inter-rater agreement requires at least two experts")
    if long.duplicated(["reaction_id", "expert_id"]).any():
        raise AnnotationValidationError("long annotation table has duplicate reaction/expert rows")
    pivot = long.pivot(index="reaction_id", columns="expert_id", values="expert_label").reindex(columns=expert_ids)
    distributions: dict[str, object] = {}
    for expert_id in expert_ids:
        values = pivot[expert_id]
        counts = {str(label): int((values == label).sum()) for label in [0, 1, 2, 3]}
        distributions[expert_id] = {
            "counts": counts,
            "proportions": {label: (count / len(values) if len(values) else None) for label, count in counts.items()},
            "abstention_rate": counts["3"] / len(values) if len(values) else None,
        }
    comparable_all = pivot.notna().all(axis=1) & (pivot != 3).all(axis=1)
    raw_exact = float((pivot.loc[comparable_all].nunique(axis=1) == 1).mean()) if comparable_all.any() else None
    pairwise: dict[str, object] = {}
    for i, left in enumerate(expert_ids):
        for right in expert_ids[i + 1 :]:
            mask = pivot[left].notna() & pivot[right].notna() & (pivot[left] != 3) & (pivot[right] != 3)
            matrix = [[0, 0, 0] for _ in range(3)]
            for a, b in zip(pivot.loc[mask, left].astype(int), pivot.loc[mask, right].astype(int)):
                matrix[int(a)][int(b)] += 1
            pairwise[f"{left}__{right}"] = {"n": int(mask.sum()), "confusion_matrix_rows_true_cols_other": matrix}
    matrix = [[None if pd.isna(pivot.loc[rid, eid]) or int(pivot.loc[rid, eid]) == 3 else int(pivot.loc[rid, eid]) for eid in expert_ids] for rid in pivot.index]
    result: dict[str, object] = {
        "expert_ids": expert_ids,
        "n_samples": int(len(pivot)),
        "label_distributions": distributions,
        "raw_exact_agreement_rate": raw_exact,
        "pairwise_confusion_matrices": pairwise,
        "samples_with_all_experts_non_abstain": int(comparable_all.sum()),
        "samples_with_any_abstain": int((~(pivot.notna() & (pivot != 3)).all(axis=1)).sum()),
        "abstain_semantics": "missing_not_ordinal_level",
    }
    if len(expert_ids) == 2:
        mask = pivot[expert_ids[0]].notna() & pivot[expert_ids[1]].notna() & (pivot[expert_ids[0]] != 3) & (pivot[expert_ids[1]] != 3)
        if int(mask.sum()) == 0:
            kappa = None
        else:
            from sklearn.metrics import cohen_kappa_score

            kappa = float(cohen_kappa_score(pivot.loc[mask, expert_ids[0]].astype(int), pivot.loc[mask, expert_ids[1]].astype(int), weights="quadratic"))
        result["agreement_method"] = "weighted_cohen_kappa_quadratic"
        result["agreement_value"] = kappa
        result["agreement_valid_n"] = int(mask.sum())
        result["agreement_excluded_n"] = int(len(pivot) - mask.sum())
        result["agreement_excluded_reason"] = "any_abstain_or_missing"
    else:
        alpha = ordinal_krippendorff_alpha(matrix)
        valid_units = sum(sum(value is not None for value in row) >= 2 for row in matrix)
        result["agreement_method"] = "ordinal_krippendorff_alpha"
        result["agreement_value"] = alpha
        result["agreement_valid_n"] = int(valid_units)
        result["agreement_excluded_n"] = int(len(matrix) - valid_units)
        result["agreement_excluded_reason"] = "fewer_than_two_non_abstain_ratings"
    result["status"] = "HUMAN_REVIEW_REQUIRED"
    return result
