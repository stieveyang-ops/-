"""Freeze the Stage 10 analysis plan before locked-test unseal."""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest().upper()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--output',default='reports/stage10_preanalysis_manifest.json'); a=ap.parse_args(); out=ROOT/a.output
 payload={"stage":10,"primary_metric":"kendall_tau_b","secondary_metrics":["spearman_rho","macro_f1","balanced_accuracy","quadratic_weighted_kappa"],"models":["A","B","C","D","E"],"bootstrap_repetitions":1000,"bootstrap_unit":"leakage_group_id","bootstrap_seed":42,"precedent_tau":[0.75,0.80,0.85],"precedent_N0":[5,10,20],"primary_precedent_tau":0.80,"primary_precedent_N0":10,"primary_delta_sc":"product_minus_max_precursor","alternate_delta_sc":"product_minus_mean_precursor","locked_test_hash":sha(ROOT/'data/splits/test_ids_locked.txt'),"final_model_hash":sha(ROOT/'artifacts/difficulty_model.pkl'),"final_model_metadata_hash":sha(ROOT/'artifacts/difficulty_model_metadata.json'),"expert_label_hash":sha(ROOT/'data/labels/final_expert_labels.parquet'),"reaction_features_hash":sha(ROOT/'data/processed/reaction_features.parquet'),"reference_corpus_hash":sha(ROOT/'data/reference/reference_reactions_clean.parquet'),"reference_embeddings_hash":sha(ROOT/'artifacts/reference_rxnfp.npy'),"code_git_commit":None,"created_at_utc":datetime.now(timezone.utc).isoformat(),"test_metrics_computed":False}
 out.parent.mkdir(parents=True,exist_ok=True)
 if out.exists():
  old=json.loads(out.read_text(encoding='utf-8'))
  keys=[k for k in payload if k not in {'created_at_utc'}]
  if any(old.get(k)!=payload.get(k) for k in keys): raise RuntimeError('BLOCKED_PREANALYSIS_MANIFEST_DRIFT')
  print(json.dumps(old,indent=2)); return 0
 out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(payload,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
