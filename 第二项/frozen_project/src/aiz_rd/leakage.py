"""Stage 10 deterministic leakage audit helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _target_set(frame: pd.DataFrame) -> set[str]:
    out: set[str] = set()
    for value in frame.get("target_ids", []):
        if isinstance(value, str):
            import json
            try:
                value = json.loads(value)
            except Exception:
                value = [value]
        if isinstance(value, (list, tuple, set)):
            out.update(str(x) for x in value)
        elif value is not None:
            out.add(str(value))
    return out


def audit_leakage(
    benchmark: pd.DataFrame,
    split_assignments: pd.DataFrame,
    reference_metadata: pd.DataFrame,
    *,
    test_hashes: set[str] | None = None,
) -> dict[str, object]:
    """Audit unique benchmark and frozen development/test assignments."""
    b = benchmark.copy()
    duplicate_hash_rows = int(b.duplicated("reaction_hash", keep=False).sum())
    duplicate_hash_count = int(max(0, duplicate_hash_rows - b.reaction_hash.nunique()))
    exact_match_count = int(b.duplicated([c for c in ["reaction_hash", "reaction_smiles"] if c in b.columns], keep=False).sum()) if {"reaction_hash", "reaction_smiles"}.issubset(b.columns) else duplicate_hash_rows
    a = split_assignments.copy()
    dev = a[a["split"].eq("development")]
    test = a[a["split"].eq("locked_test")]
    target_overlap = len(_target_set(dev) & _target_set(test))
    reaction_overlap = len(set(dev.reaction_hash.astype(str)) & set(test.reaction_hash.astype(str)))
    group_overlap = len(set(dev.leakage_group_id.astype(str)) & set(test.leakage_group_id.astype(str)))
    test_hashes = set(test_hashes or set(test.reaction_hash.astype(str)))
    reference_hashes = set(reference_metadata.reaction_hash.astype(str))
    raw_overlap = len(reference_hashes & test_hashes)
    label_conflicts = 0
    if "expert_label" in a.columns:
        grouped = a.dropna(subset=["expert_label"]).groupby("reaction_hash")["expert_label"].nunique()
        label_conflicts = int((grouped > 1).sum())
    # The frozen Stage 5 query artifact is deployment mode.  Effective overlap
    # is only zero when benchmark exact exclusion is demonstrably applied.
    exclusion_verified = bool(test_hashes.isdisjoint(reference_hashes))
    effective_overlap = 0 if exclusion_verified else raw_overlap
    return {
        "exact_match_count": exact_match_count,
        "duplicate_hash_count": duplicate_hash_count,
        "train_test_target_overlap": int(target_overlap),
        "train_test_reaction_overlap": int(reaction_overlap),
        "train_test_leakage_group_overlap": int(group_overlap),
        "reference_test_exact_overlap_raw": int(raw_overlap),
        "reference_test_exact_overlap": int(effective_overlap),
        "reference_test_exact_overlap_effective": int(effective_overlap),
        "reference_train_exact_overlap_raw": int(len(reference_hashes & set(dev.reaction_hash.astype(str)))),
        "benchmark_exact_exclusion_verified": exclusion_verified,
        "label_duplicate_conflict_count": label_conflicts,
        "status": "PASS" if (exact_match_count == 0 and duplicate_hash_count == 0 and target_overlap == 0 and reaction_overlap == 0 and group_overlap == 0 and effective_overlap == 0 and label_conflicts == 0) else "BLOCKED",
    }
