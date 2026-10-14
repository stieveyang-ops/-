"""Create immutable Stage 10 v2.2 pre-analysis manifest."""
from __future__ import annotations
import argparse, hashlib, importlib.metadata, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  block=f.read(1024*1024)
  while block:
   h.update(block); block=f.read(1024*1024)
 return h.hexdigest().upper()
def version(name):
 try: return importlib.metadata.version(name)
 except Exception: return None
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--output',default='reports/stage10_preanalysis_manifest_v22.json'); a=ap.parse_args()
 cfg=ROOT/'reports/stage10_preanalysis_config_v22.json'; out=ROOT/a.output
 payload={
  'stage':10,'cycle_version':'stage10_v2.2','status':'FROZEN',
  'config_path':'reports/stage10_preanalysis_config_v22.json','config_sha256':sha(cfg),
  'locked_test_path':'data/splits/test_ids_locked.txt','locked_test_sha256':sha(ROOT/'data/splits/test_ids_locked.txt'),
  'stage8_model_path':'artifacts/difficulty_model.pkl','stage8_model_sha256':sha(ROOT/'artifacts/difficulty_model.pkl'),
  'stage8_model_metadata_path':'artifacts/difficulty_model_metadata.json','stage8_model_metadata_sha256':sha(ROOT/'artifacts/difficulty_model_metadata.json'),
  'stage9_ranking_path':'outputs/scored_routes.parquet','stage9_ranking_sha256':sha(ROOT/'outputs/scored_routes.parquet'),
  'stage8_manifest_sha256':sha(ROOT/'reports/stage8_manifest.json'),'stage9_manifest_sha256':sha(ROOT/'reports/stage9_manifest.json'),
  'expert_label_sha256':sha(ROOT/'data/labels/final_expert_labels.parquet'),'reaction_features_sha256':sha(ROOT/'data/processed/reaction_features.parquet'),
  'reference_corpus_sha256':sha(ROOT/'data/reference/reference_reactions_clean.parquet'),'reference_embeddings_sha256':sha(ROOT/'artifacts/reference_rxnfp.npy'),
  'primary_metric':'kendall_tau_b','secondary_metrics':['spearman_rho','macro_f1','balanced_accuracy','quadratic_weighted_kappa'],
  'models':['A','B','C','D','E'],'bootstrap_repetitions':1000,'bootstrap_unit':'leakage_group_id','bootstrap_seed':42,
  'precedent_tau':[0.75,0.8,0.85],'precedent_N0':[5,10,20],'primary_precedent_tau':0.8,'primary_precedent_N0':10,
  'primary_delta_sc':'product_minus_max_precursor','alternate_delta_sc':'product_minus_mean_precursor',
  'primary_benchmark_excludes_abstain':True,'leave_one_out_models':[['d_prec','d_sc'],['d_feas','d_sc'],['d_feas','d_prec']],
  'python_version':sys.version,'package_versions':{k:version(k) for k in ['numpy','pandas','scipy','scikit-learn','statsmodels','pyarrow']},
  'git_commit':None,'git_commit_reason':'Project directory is not a Git worktree',
  'locked_test_modified':'NO','test_metrics_computed_before_unseal':False,'test_tuning':False,'model_retrained':False,'stage11_started':False,
  'created_at_utc':datetime.now(timezone.utc).isoformat()
 }
 if out.exists():
  old=json.loads(out.read_text(encoding='utf-8')); keys=[k for k in payload if k not in {'created_at_utc','status'}]
  if any(old.get(k)!=payload.get(k) for k in keys): raise RuntimeError('BLOCKED_STAGE10_V22_PREANALYSIS_DRIFT')
  print(json.dumps(old,indent=2,ensure_ascii=False)); return 0
 out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(payload,indent=2,ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
