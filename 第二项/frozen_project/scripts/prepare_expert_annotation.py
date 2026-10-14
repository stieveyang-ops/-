"""Prepare the Stage 7 blind expert-annotation package and stop at Gate A."""
from __future__ import annotations
import argparse, hashlib, json, platform, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path: sys.path.insert(0, str(ROOT / "src"))
from aiz_rd.annotation import (  # noqa: E402
    KEY_COLUMNS, REACTION_ID_SALT, VISIBLE_COLUMNS, AnnotationValidationError,
    atomic_write_csv, atomic_write_json, atomic_write_parquet, atomic_write_text,
    audit_blinded_frame, deduplicate_candidates, make_annotation_tables, sha256,
    stratified_sample, validate_stage6_features,
)

def _json(path: Path) -> dict:
    if not path.is_file(): raise AnnotationValidationError(f"missing required JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

def protocol_text() -> str:
    return """# EXPERT ANNOTATION PROTOCOL

Version: stage7_expert_annotation_protocol_v1

Judge each substrate-specific transformation using only the supplied structures
and your existing organic-synthesis knowledge. Exact conditions are unknown,
but reasonable conventional conditions may be selected. Do not use literature
searches or external databases for individual reactions.

Labels (write only the literal integer):
- 0 Easy: mature transformation/substrate combination, no major obstacle.
- 1 Medium: plausible but with meaningful structural, selectivity, or
  compatibility risk; some optimization is expected.
- 2 Difficult: uncommon or clearly challenging; substantial optimization or
  failure risk is expected.
- 3 Uncertain/Abstain: structure alone is insufficient for a responsible
  judgment. Do not guess.

Exclude price/availability, safety/toxicity/environment, yield, AiZynthFinder
route length/state score/rank, equipment, operator skill, and scale-up.
Annotate independently and do not discuss samples before submission. Do not
modify reaction_id, reaction_smiles, reactants, or product. Return exactly the
same five columns, with expert_label filled by 0/1/2/3 and no index column.
"""

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=str(ROOT / "data/processed/reaction_features.parquet"))
    ap.add_argument("--steps", default=str(ROOT / "data/processed/reaction_steps_raw.parquet"))
    ap.add_argument("--target-n", type=int, default=300)
    ap.add_argument("--minimum-n", type=int, default=200)
    ap.add_argument("--n-experts", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output-dir", default=str(ROOT / "data/labels"))
    ap.add_argument("--report", default=str(ROOT / "reports/stage7_sampling_report.json"))
    ap.add_argument("--manifest", default=str(ROOT / "reports/stage7_annotation_manifest.json"))
    args = ap.parse_args()
    report = {"stage": 7, "status": "BLOCKED", "created_at_utc": datetime.now(timezone.utc).isoformat(), "errors": []}
    try:
        if args.n_experts < 2 or args.target_n < args.minimum_n or args.minimum_n < 1:
            raise AnnotationValidationError("invalid Stage 7 sample/expert parameters")
        features_path, steps_path = Path(args.features).resolve(), Path(args.steps).resolve()
        outdir, report_path, manifest_path = Path(args.output_dir).resolve(), Path(args.report).resolve(), Path(args.manifest).resolve()
        s6_report_path, s6_manifest_path = ROOT / "reports/stage6_feature_pipeline_report.json", ROOT / "reports/stage6_manifest.json"
        s6_report, s6_manifest = _json(s6_report_path), _json(s6_manifest_path)
        if s6_report.get("status") != "PASS" or s6_manifest.get("status") != "PASS": raise AnnotationValidationError("Stage 6 is not PASS")
        if not features_path.is_file() or not steps_path.is_file(): raise AnnotationValidationError("Stage 6/2 input missing")
        if s6_manifest.get("output", {}).get("sha256", "").upper() != sha256(features_path): raise AnnotationValidationError("Stage 6 feature hash drift")
        steps_hash = s6_manifest.get("input_files", {}).get("reaction_steps_raw", {}).get("sha256")
        if steps_hash and steps_hash.upper() != sha256(steps_path): raise AnnotationValidationError("Stage 2 hash drift")
        features, steps = pd.read_parquet(features_path), pd.read_parquet(steps_path)
        validate_stage6_features(features, steps)
        if len(features) != len(steps) or set(map(tuple, features[KEY_COLUMNS].to_numpy())) != set(map(tuple, steps[KEY_COLUMNS].to_numpy())): raise AnnotationValidationError("Stage 6/2 key mismatch")
        for col in ["reaction_smiles", "product_smiles", "precursor_smiles"]:
            if not features.set_index(KEY_COLUMNS)[col].astype("string").sort_index().equals(steps.set_index(KEY_COLUMNS)[col].astype("string").sort_index()): raise AnnotationValidationError(f"Stage 6/2 {col} mismatch")
        candidates = deduplicate_candidates(features)
        eligible_n = len(candidates)
        if eligible_n < args.minimum_n: raise AnnotationValidationError(f"eligible unique candidates {eligible_n} < minimum {args.minimum_n}")
        actual_n = min(args.target_n, eligible_n)
        sampled, strata = stratified_sample(candidates, actual_n, args.seed)
        tables = make_annotation_tables(sampled, args.n_experts, args.seed)
        master, key, experts = tables["master"], tables["key"], tables["experts"]
        paths = [outdir / "expert_annotation_blinded.csv", outdir / "expert_annotation_key.parquet", outdir / "EXPERT_ANNOTATION_PROTOCOL.md"] + [outdir / "blinded" / f"annotation_{eid}.csv" for eid in experts]
        existing = [str(p) for p in paths if p.exists()]
        if existing: raise AnnotationValidationError(f"refusing to overwrite existing package files: {existing}")
        outdir.mkdir(parents=True, exist_ok=True)
        atomic_write_csv(master, outdir / "expert_annotation_blinded.csv")
        atomic_write_parquet(key, outdir / "expert_annotation_key.parquet")
        atomic_write_text(outdir / "EXPERT_ANNOTATION_PROTOCOL.md", protocol_text())
        master_audit = audit_blinded_frame(pd.read_csv(outdir / "expert_annotation_blinded.csv", dtype=str, keep_default_na=False), expected_ids=set(master.reaction_id))
        expert_hashes, expert_audits = {}, {}
        for eid, frame in experts.items():
            p = outdir / "blinded" / f"annotation_{eid}.csv"; atomic_write_csv(frame, p)
            expert_audits[eid] = audit_blinded_frame(pd.read_csv(p, dtype=str, keep_default_na=False), expected_ids=set(master.reaction_id)); expert_hashes[eid] = sha256(p)
        protocol = outdir / "EXPERT_ANNOTATION_PROTOCOL.md"
        report.update({"status":"READY_FOR_HUMAN_ANNOTATION", "input_candidate_rows":len(features), "unique_reaction_hashes":int(features.reaction_hash.nunique()), "eligible_unique_reactions":eligible_n, "target_n":args.target_n, "minimum_acceptable_n":args.minimum_n, "actual_n":actual_n, "seed":args.seed, "n_experts":args.n_experts, "expert_ids":list(experts), "per_expert_shuffle_seeds":tables["shuffle_seeds"], "sampling":strata, "excluded_counts_by_reason":{"not_sampled_after_stratified_quota":eligible_n-actual_n}, "reaction_hash_deduplication":{"input_rows":len(features),"unique_hashes":eligible_n,"duplicate_occurrences_collapsed":len(features)-eligible_n}, "blinding":{"visible_columns":VISIBLE_COLUMNS,"forbidden_field_audit":"PASS","master_audit":master_audit,"expert_audits":expert_audits}, "files":{"expert_annotation_blinded":str(outdir/"expert_annotation_blinded.csv"),"expert_annotation_key":str(outdir/"expert_annotation_key.parquet"),"protocol":str(protocol),"expert_files":{eid:str(outdir/"blinded"/f"annotation_{eid}.csv") for eid in experts}}, "hashes":{"features_sha256":sha256(features_path),"steps_sha256":sha256(steps_path),"stage6_report_sha256":sha256(s6_report_path),"stage6_manifest_sha256":sha256(s6_manifest_path),"blinded_master_sha256":sha256(outdir/"expert_annotation_blinded.csv"),"hidden_key_sha256":sha256(outdir/"expert_annotation_key.parquet"),"protocol_sha256":sha256(protocol),"per_expert_template_sha256":expert_hashes,"reaction_id_salt_sha256":hashlib.sha256(REACTION_ID_SALT.encode()).hexdigest().upper()},"human_gate":"STOP_AFTER_GATE_A","expert_labels_generated_by_codex":False})
        manifest = {"stage":7,"status":"READY_FOR_HUMAN_ANNOTATION","created_at_utc":report["created_at_utc"],"git_commit":None,"git_commit_reason":"Project directory is not a Git worktree","python_version":platform.python_version(),"input_reaction_features_sha256":sha256(features_path),"input_stage6_report_sha256":sha256(s6_report_path),"sampling_seed":args.seed,"sampling_target_n":args.target_n,"sampling_minimum_n":args.minimum_n,"actual_sample_n":actual_n,"n_experts":args.n_experts,"expert_ids":list(experts),"per_expert_shuffle_seeds":tables["shuffle_seeds"],"reaction_id_scheme":"RXNANN_ + SHA256(reaction_hash + frozen_stage7_salt)[:16]","reaction_id_salt_hash":report["hashes"]["reaction_id_salt_sha256"],"sampling_bin_edges":strata["bin_edges"],"blinded_master_sha256":report["hashes"]["blinded_master_sha256"],"hidden_key_sha256":report["hashes"]["hidden_key_sha256"],"per_expert_template_sha256":expert_hashes,"agreement_method":"pending human annotations","abstain_semantics":"missing_not_ordinal_level","pytest_summary":"pending Stage 7 tests","protocol_version":"stage7_expert_annotation_protocol_v1","human_gate":"STOP_AFTER_GATE_A"}
        atomic_write_json(report, report_path); atomic_write_json(manifest, manifest_path); print("READY_FOR_HUMAN_ANNOTATION"); return 0
    except Exception as exc:
        report["errors"] = [f"{type(exc).__name__}: {exc}"]; atomic_write_json(report, Path(args.report).resolve()); print("BLOCKED"); print(json.dumps(report, indent=2, ensure_ascii=False)); return 1

if __name__ == "__main__": raise SystemExit(main())
