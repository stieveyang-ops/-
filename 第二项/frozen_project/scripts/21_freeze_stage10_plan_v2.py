"""Create an immutable versioned Stage 10 v2 pre-analysis manifest."""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest().upper()
def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default='reports/stage10_preanalysis_manifest_v2.json'); a=ap.parse_args()
    cfg=ROOT/'reports/stage10_preanalysis_config_v2.json'; out=ROOT/a.output
    required=[cfg,ROOT/'data/splits/test_ids_locked.txt',ROOT/'artifacts/difficulty_model.pkl',ROOT/'artifacts/difficulty_model_metadata.json',ROOT/'outputs/scored_routes.parquet',ROOT/'reports/stage8_manifest.json',ROOT/'reports/stage9_manifest.json']
    if not all(p.exists() for p in required): raise RuntimeError('BLOCKED_STAGE10_V2_PREREQUISITE_MISSING')
    payload={
      'stage':10,'cycle_version':'stage10_v2','status':'FROZEN',
      'config_path':str(cfg.relative_to(ROOT)).replace('\\','/'),'config_sha256':sha(cfg),
      'primary_metric':'kendall_tau_b','secondary_metrics':['spearman_rho','macro_f1','balanced_accuracy','quadratic_weighted_kappa'],
      'models':['A','B','C','D','E'],'bootstrap_repetitions':1000,'bootstrap_unit':'leakage_group_id','bootstrap_seed':42,
      'precedent_tau':[0.75,0.80,0.85],'precedent_N0':[5,10,20],'primary_precedent_tau':0.80,'primary_precedent_N0':10,
      'primary_delta_sc':'product_minus_max_precursor','alternate_delta_sc':'product_minus_mean_precursor',
      'locked_test_path':'data/splits/test_ids_locked.txt','locked_test_sha256':sha(ROOT/'data/splits/test_ids_locked.txt'),
      'stage8_model_path':'artifacts/difficulty_model.pkl','stage8_model_sha256':sha(ROOT/'artifacts/difficulty_model.pkl'),
      'stage8_model_metadata_path':'artifacts/difficulty_model_metadata.json','stage8_model_metadata_sha256':sha(ROOT/'artifacts/difficulty_model_metadata.json'),
      'stage9_ranking_path':'outputs/scored_routes.parquet','stage9_ranking_sha256':sha(ROOT/'outputs/scored_routes.parquet'),
      'stage8_manifest_sha256':sha(ROOT/'reports/stage8_manifest.json'),'stage9_manifest_sha256':sha(ROOT/'reports/stage9_manifest.json'),
      'expert_label_sha256':sha(ROOT/'data/labels/final_expert_labels.parquet'),'reaction_features_sha256':sha(ROOT/'data/processed/reaction_features.parquet'),
      'reference_corpus_sha256':sha(ROOT/'data/reference/reference_reactions_clean.parquet'),'reference_embeddings_sha256':sha(ROOT/'artifacts/reference_rxnfp.npy'),
      'locked_test_modified':'NO','test_metrics_computed_before_unseal':False,'test_tuning':False,'model_retrained':False,'stage11_started':False,
      'created_at_utc':datetime.now(timezone.utc).isoformat()
    }
    if out.exists():
        old=json.loads(out.read_text(encoding='utf-8'))
        compare={k:v for k,v in payload.items() if k not in {'created_at_utc','status'}}
        if any(old.get(k)!=v for k,v in compare.items()): raise RuntimeError('BLOCKED_STAGE10_V2_PREANALYSIS_DRIFT')
        print(json.dumps(old,indent=2,ensure_ascii=False)); return 0
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(payload,indent=2,ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
