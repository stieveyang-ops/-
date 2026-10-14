"""ORD reference corpus preparation helpers and RXNFP nearest-neighbour API."""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from aiz_rd.chemistry import canonicalize_reaction, reaction_hash


def transformation_only(smiles: str) -> str:
    if not isinstance(smiles, str):
        raise ValueError("reaction SMILES must be a string")
    # Accept the two canonical transformation sections (``reactants>>products``)
    # or the standard three-section form (``reactants>agents>products``).
    # A single ``>`` is not a valid two-section reaction representation.
    if ">>" in smiles:
        if smiles.count(">>") != 1:
            raise ValueError("reaction must contain exactly one >> separator")
        reactants, products = smiles.split(">>", 1)
    else:
        parts = smiles.split(">")
        if len(parts) != 3:
            raise ValueError("reaction must contain reactants>>products or reactants>agents>products")
        reactants, _, products = parts
    if not reactants.strip():
        raise ValueError("empty reactant side")
    if not products.strip():
        raise ValueError("empty product side")
    return f"{reactants}>>{products}"


def ord_message_to_transformation(message) -> str:
    """Generate reactants>>products from ORD roles using ord-schema helpers.

    This deliberately reads ORD's typed reaction roles instead of splitting the
    helper's full string: agent structures can themselves contain ``>`` in
    directional-bond SMILES. Reactant/product disconnected components are kept
    exactly; only REAGENT/SOLVENT/CATALYST roles are excluded.
    """
    from ord_schema.message_helpers import smiles_from_compound
    from ord_schema.proto import reaction_pb2

    roles = reaction_pb2.ReactionRole
    reactant_roles = {roles.REACTANT, roles.UNSPECIFIED}
    product_roles = {roles.PRODUCT, roles.UNSPECIFIED}
    reactants, products = set(), set()
    for key in sorted(message.inputs):
        for compound in message.inputs[key].components:
            if compound.reaction_role in reactant_roles:
                reactants.add(smiles_from_compound(compound, canonical=True))
    for outcome in message.outcomes:
        for product in outcome.products:
            if product.reaction_role in product_roles:
                products.add(smiles_from_compound(product, canonical=True))
    if not reactants:
        raise ValueError("ORD reaction has no parseable reactants")
    if not products:
        raise ValueError("ORD reaction has no parseable products")
    return ".".join(sorted(reactants)) + ">>" + ".".join(sorted(products))


def _stable_results(distances, indices, metadata, query_hash, mode, top_k):
    candidates = []
    for d, i in zip(distances, indices):
        row = metadata.iloc[int(i)]
        rh = str(row.reaction_hash)
        if mode == "benchmark" and rh == query_hash:
            continue
        sim = min(1.0, max(0.0, 1.0 - float(d)))
        candidates.append((sim, rh, str(row.reference_id), row))
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    out=[]
    for rank, (sim, _, _, row) in enumerate(candidates[:top_k], 1):
        out.append({"rank": rank, "reference_id": str(row.reference_id), "similarity": float(sim), "reaction_hash": str(row.reaction_hash), "reaction_smiles": str(row.reaction_smiles), "source": str(row.source), "duplicate_count": int(row.duplicate_count)})
    return out


@dataclass(frozen=True)
class PrecedentScore:
    """Full-corpus precedent statistics for one canonical reaction."""

    search_mode: str
    tau: float
    n0: float
    s_max: float
    n_analog: int
    p_prec: float
    d_prec: float
    n_exact_hash_excluded: int
    nearest_reference_id: str
    nearest_reference_hash: str
    nearest_reference_similarity: float


def compute_precedent_score(
    similarities: np.ndarray,
    metadata,
    query_hash: str,
    *,
    mode: str,
    tau: float = 0.80,
    n0: float = 10.0,
) -> PrecedentScore:
    """Compute the approved full-corpus precedent formula.

    ``similarities`` must contain one cosine similarity per reference row in
    exactly the same order as ``metadata``. Exact-hash exclusion in benchmark
    mode is applied before both ``S_max`` and ``N_analog``.
    """
    import pandas as pd

    if mode not in {"deployment", "benchmark"}:
        raise ValueError("mode must be deployment or benchmark")
    if not math.isfinite(float(tau)) or not 0.0 <= float(tau) <= 1.0:
        raise ValueError("tau must be finite and in [0,1]")
    if not math.isfinite(float(n0)) or float(n0) <= 0.0:
        raise ValueError("n0 must be finite and positive")
    values = np.asarray(similarities, dtype=np.float64).reshape(-1)
    if len(values) != len(metadata) or not np.isfinite(values).all():
        raise ValueError("similarity/metadata mismatch or non-finite similarity")
    # Stage 4 defines public similarity as clip(raw cosine, 0, 1). Negative
    # cosine values are therefore valid and contribute zero precedent support;
    # only an upper-bound violation beyond floating-point tolerance is invalid.
    if np.any(values > 1.0 + 1e-6):
        raise ValueError("similarity outside cosine range")
    values = np.clip(values, 0.0, 1.0)
    hashes = metadata["reaction_hash"].astype(str).to_numpy()
    exact_mask = hashes == str(query_hash)
    eligible = ~exact_mask if mode == "benchmark" else np.ones(len(values), dtype=bool)
    if not np.any(eligible):
        raise RuntimeError("BLOCKED_NO_ELIGIBLE_REFERENCE: exact-hash exclusion removed all references")
    eligible_idx = np.flatnonzero(eligible)
    # Stable deterministic ordering: similarity descending, reaction hash, id.
    refs = metadata.iloc[eligible_idx]
    order = sorted(
        range(len(eligible_idx)),
        key=lambda j: (-float(values[eligible_idx[j]]), str(refs.iloc[j].reaction_hash), str(refs.iloc[j].reference_id)),
    )
    best = eligible_idx[order[0]]
    s_max = float(values[best])
    n_analog = int(np.count_nonzero(values[eligible] >= float(tau)))
    p_prec = float(s_max * (1.0 - math.exp(-float(n_analog) / float(n0)))) if n_analog else 0.0
    p_prec = min(1.0, max(0.0, p_prec))
    d_prec = 1.0 - p_prec
    row = metadata.iloc[int(best)]
    return PrecedentScore(
        search_mode=mode,
        tau=float(tau),
        n0=float(n0),
        s_max=s_max,
        n_analog=n_analog,
        p_prec=p_prec,
        d_prec=d_prec,
        n_exact_hash_excluded=int(np.count_nonzero(exact_mask)) if mode == "benchmark" else 0,
        nearest_reference_id=str(row.reference_id),
        nearest_reference_hash=str(row.reaction_hash),
        nearest_reference_similarity=s_max,
    )


class ReactionPrecedentIndex:
    def __init__(self, embedding_path, metadata_path, index_path, rxnfp_runtime, top_k=100):
        import pandas as pd, joblib
        self.embeddings = np.load(embedding_path, mmap_mode="r")
        self._reference_matrix = np.asarray(self.embeddings, dtype=np.float64)
        self.metadata = pd.read_parquet(metadata_path)
        self.index = joblib.load(index_path)
        self.runtime = rxnfp_runtime
        self.top_k = int(top_k)
        if self.embeddings.shape[0] != len(self.metadata): raise ValueError("embedding metadata row mismatch")

    def query_reaction_smiles(self, reaction_smiles: str, *, mode: str = "deployment", top_k: int | None = None):
        if mode not in {"deployment", "benchmark"}: raise ValueError("mode must be deployment or benchmark")
        canonical = transformation_only(reaction_smiles)
        reactants, products = canonical.split(">>", 1)
        p, prod, canonical_reaction = canonicalize_reaction(reactants.split("."), products)
        if canonical_reaction != reaction_smiles: raise ValueError("BLOCKED_QUERY_CANONICALIZATION_DRIFT")
        vec = np.asarray(self.runtime.embed([canonical_reaction]), dtype=np.float32)
        return self.query_vector(vec[0], reaction_hash(canonical_reaction), mode=mode, top_k=top_k)

    def query_vector(self, vector: np.ndarray, query_hash: str, *, mode: str = "deployment", top_k: int | None = None):
        if mode not in {"deployment", "benchmark"}: raise ValueError("mode must be deployment or benchmark")
        vec = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        norm = np.linalg.norm(vec, axis=1, keepdims=True)
        if vec.shape[1] != 256 or not np.isfinite(vec).all() or float(norm[0, 0]) <= 0: raise ValueError("invalid query embedding")
        vec = vec / norm
        k = min(len(self.metadata), int(top_k or self.top_k) + (1 if mode == "benchmark" else 0))
        distances, indices = self.index.kneighbors(vec, n_neighbors=max(1, k))
        return _stable_results(distances[0], indices[0], self.metadata, query_hash, mode, int(top_k or self.top_k))

    def full_corpus_score(self, vector: np.ndarray, query_hash: str, *, mode: str = "deployment", tau: float = 0.80, n0: float = 10.0) -> PrecedentScore:
        """Compute exact ``S_max``/``N_analog`` over every reference row."""
        vec = np.asarray(vector, dtype=np.float64).reshape(-1)
        if vec.shape != (256,) or not np.isfinite(vec).all():
            raise ValueError("invalid query embedding")
        norm = float(np.linalg.norm(vec))
        if norm <= 0.0:
            raise ValueError("zero query embedding")
        vec = vec / norm
        similarities = self._reference_matrix @ vec
        return compute_precedent_score(similarities, self.metadata, query_hash, mode=mode, tau=tau, n0=n0)

    def query_reaction_row(self, reaction_hash_value: str, reaction_smiles: str, *, mode: str, top_k: int | None = None):
        return self.query_reaction_smiles(reaction_smiles, mode=mode, top_k=top_k)


def isolated_scratch_parent() -> str | None:
    """RXNFP 隔离进程的临时目录父路径（优先包内目录，见 prospective_score 同名函数说明）。"""
    candidate = Path(__file__).resolve().parents[3] / "_runtime_tmp"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return str(candidate)
    except Exception:
        return None

class RXNFPRuntime:
    def __init__(self, interpreter: str | None = None):
        self.interpreter = interpreter or str(Path(__file__).resolve().parents[2] / ".conda-rxnfp" / "python.exe")
        self.worker = Path(__file__).resolve().parents[2] / "scripts" / "rxnfp_worker.py"
        self.generator = None
        try:
            from rxnfp.transformer_fingerprints import RXNBERTFingerprintGenerator, get_default_model_and_tokenizer
            model, tokenizer = get_default_model_and_tokenizer(model="bert_ft", force_no_cuda=True)
            self.generator = RXNBERTFingerprintGenerator(model, tokenizer, force_no_cuda=True)
        except ImportError:
            if not Path(self.interpreter).is_file() or not self.worker.is_file():
                raise RuntimeError("BLOCKED_RXNFP_RUNTIME_UNRESOLVED")
    def embed(self, reactions: list[str]) -> np.ndarray:
        return self.embed_many(reactions)

    def embed_many(self, reactions: list[str]) -> np.ndarray:
        if self.generator is not None:
            arr = np.asarray(self.generator.convert_batch(reactions), dtype=np.float32)
        else:
            with tempfile.TemporaryDirectory(prefix="rxnfp_query_", dir=isolated_scratch_parent()) as td:
                inp = Path(td) / "input.txt"; out = Path(td) / "output.npy"
                inp.write_text("\n".join(reactions), encoding="utf-8")
                proc = subprocess.run([self.interpreter, str(self.worker), str(inp), str(out)], capture_output=True, text=True)
                if proc.returncode != 0:
                    raise RuntimeError(f"RXNFP isolated worker failed: {proc.stderr[-1000:]}")
                arr = np.load(out)
        if arr.ndim != 2 or arr.shape[1] != 256: raise ValueError(f"RXNFP dimension mismatch: {arr.shape}")
        if not np.isfinite(arr).all(): raise ValueError("non-finite RXNFP embedding")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        if np.any(norms <= 0): raise ValueError("zero RXNFP embedding")
        return arr / norms
