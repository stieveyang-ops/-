"""Deterministic reaction-level leakage grouping and locked split."""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold


def _find(parent, x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent, a, b):
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[rb] = ra


def build_modeling_table(features: pd.DataFrame, final_labels: pd.DataFrame):
    required = {"reaction_hash", "target_id", "p_feas", "d_feas", "p_prec", "d_prec", "d_sc"}
    if not required.issubset(features.columns):
        raise ValueError(f"missing feature columns: {sorted(required - set(features.columns))}")
    if features[list(required)].isna().any().any():
        raise ValueError("missing feature values")
    if not np.isfinite(features[["p_feas", "d_feas", "p_prec", "d_prec", "d_sc"]].to_numpy(float)).all():
        raise ValueError("non-finite feature values")
    if ((features[["p_feas", "d_feas", "p_prec", "d_prec", "d_sc"]] < 0) | (features[["p_feas", "d_feas", "p_prec", "d_prec", "d_sc"]] > 1)).any().any():
        raise ValueError("feature outside [0,1]")
    if not np.allclose(features.d_feas, 1 - features.p_feas, atol=1e-12, rtol=0):
        raise ValueError("d_feas identity failed")
    if not np.allclose(features.d_prec, 1 - features.p_prec, atol=1e-12, rtol=0):
        raise ValueError("d_prec identity failed")
    labels = final_labels.copy()
    if labels.reaction_hash.duplicated().any() or labels.reaction_hash.isna().any():
        raise ValueError("final labels reaction_hash must be unique and non-missing")
    if not set(labels.final_status.astype(str)).issubset({"LABELED", "ABSTAIN"}):
        raise ValueError("invalid final label status")
    if ((labels.final_status == "LABELED") & ~labels.expert_label.isin([0, 1, 2])).any():
        raise ValueError("LABELED rows must have labels 0,1,2")
    if ((labels.final_status == "ABSTAIN") & labels.expert_label.notna()).any():
        raise ValueError("ABSTAIN rows must have null expert_label")
    rows = []
    label_map = labels.set_index("reaction_hash")
    for reaction_hash, group in features.groupby("reaction_hash", sort=True):
        values = group[["p_feas", "d_feas", "p_prec", "d_prec", "d_sc"]].to_numpy(float)
        if not np.allclose(values, values[0], atol=1e-12, rtol=0):
            raise ValueError(f"inconsistent core features for reaction_hash={reaction_hash}")
        if reaction_hash not in label_map.index:
            continue
        label_row = label_map.loc[reaction_hash]
        target_ids = sorted({str(x) for x in group.target_id.tolist()})
        rows.append({"reaction_hash": str(reaction_hash), "target_ids": target_ids, "target_id_count": len(target_ids), "p_feas": float(values[0, 0]), "d_feas": float(values[0, 1]), "p_prec": float(values[0, 2]), "d_prec": float(values[0, 3]), "d_sc": float(values[0, 4]), "expert_label": (None if pd.isna(label_row.expert_label) else int(label_row.expert_label)), "final_status": str(label_row.final_status)})
    table = pd.DataFrame(rows)
    if table.empty:
        raise ValueError("no final labels matched feature table")
    if table.reaction_hash.duplicated().any():
        raise ValueError("modeling table contains duplicate reaction_hash")
    return table


def assign_leakage_groups(table: pd.DataFrame):
    parent = {}
    for row in table.itertuples(index=False):
        reaction_node = "R:" + row.reaction_hash
        _find(parent, reaction_node)
        for target_id in row.target_ids:
            _union(parent, reaction_node, "T:" + str(target_id))
    groups = {}
    for row in table.itertuples(index=False):
        roots = {_find(parent, "R:" + row.reaction_hash)}
        roots.update(_find(parent, "T:" + str(t)) for t in row.target_ids)
        root = sorted(roots)[0]
        groups.setdefault(root, len(groups))
    return table.assign(leakage_group_id=table.reaction_hash.map(lambda h: f"LG_{groups[_find(parent, 'R:' + h)]:04d}"))


def locked_split(table: pd.DataFrame, seed=42):
    labeled = table[table.final_status == "LABELED"].copy()
    if set(labeled.expert_label.astype(int).unique()) != {0, 1, 2}:
        raise ValueError("development candidate does not contain all classes")
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    folds = list(splitter.split(labeled, labeled.expert_label.astype(int), labeled.leakage_group_id))
    train_idx, test_idx = folds[0]
    development = labeled.iloc[train_idx].copy()
    locked_test = labeled.iloc[test_idx].copy()
    if set(development.reaction_hash) & set(locked_test.reaction_hash):
        raise ValueError("reaction leakage across split")
    if set(development.leakage_group_id) & set(locked_test.leakage_group_id):
        raise ValueError("leakage group across split")
    dev_targets = set(t for values in development.target_ids for t in values)
    test_targets = set(t for values in locked_test.target_ids for t in values)
    if dev_targets & test_targets:
        raise ValueError("target leakage across split")
    return development, locked_test, "StratifiedGroupKFold", folds
