"""Run and record every mandatory Stage 10 v2 pre-unseal check."""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
def run(cmd):
    t=datetime.now(timezone.utc); p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True); return {'command':' '.join(cmd),'started_at_utc':t.isoformat(),'finished_at_utc':datetime.now(timezone.utc).isoformat(),'exit_code':p.returncode,'stdout_tail':p.stdout[-4000:],'stderr_tail':p.stderr[-4000:],'status':'PASS' if p.returncode==0 else 'FAIL'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--manifest',default='reports/stage10_preanalysis_manifest_v2.json'); ap.add_argument('--output',default='reports/stage10_preunseal_test_report_v2.json'); a=ap.parse_args()
 manifest=ROOT/a.manifest; out=ROOT/a.output
 if not manifest.exists(): raise RuntimeError('BLOCKED_STAGE10_V2_PREANALYSIS_MISSING')
 m=json.loads(manifest.read_text(encoding='utf-8'))
 checks=[]
 specialized=['tests/test_stage10_models.py','tests/test_stage10_metrics.py','tests/test_cluster_bootstrap.py','tests/test_ablation.py','tests/test_precedent_sensitivity.py','tests/test_scscore_sensitivity.py','tests/test_leakage_audit.py','tests/test_stage10_integrity.py']
 checks.append(run([r'E:\Anaconda\envs\aizynth\python.exe','-m','pytest','-q',*specialized]))
 checks.append(run([r'E:\Anaconda\envs\aizynth\python.exe','-m','pytest','-q']))
 leakage=run([r'E:\Anaconda\envs\aizynth\python.exe','scripts/12_leakage_audit.py']); checks.append(leakage)
 hash_checks={
  'locked_test_sha256': {'expected':m['locked_test_sha256'],'actual':sha(ROOT/'data/splits/test_ids_locked.txt')},
  'stage8_model_sha256': {'expected':m['stage8_model_sha256'],'actual':sha(ROOT/'artifacts/difficulty_model.pkl')},
  'stage8_model_metadata_sha256': {'expected':m['stage8_model_metadata_sha256'],'actual':sha(ROOT/'artifacts/difficulty_model_metadata.json')},
  'stage9_ranking_sha256': {'expected':m['stage9_ranking_sha256'],'actual':sha(ROOT/'outputs/scored_routes.parquet')},
  'preanalysis_manifest_sha256': {'expected':sha(manifest),'actual':sha(manifest)}
 }
 for x in hash_checks.values(): x['status']='PASS' if x['expected']==x['actual'] else 'FAIL'
 formal=['data/benchmark/stage10_benchmark_reactions.parquet','outputs/stage10_locked_test_predictions.parquet','reports/benchmark_results.csv','reports/benchmark_results.json','reports/bootstrap_metrics.parquet','reports/model_pairwise_differences.csv','reports/ablation_results.csv','reports/precedent_sensitivity_results.csv','reports/scscore_sensitivity_results.csv','reports/stage10_manifest.json']
 artifact_state={p:(ROOT/p).exists() for p in formal}
 # Pre-unseal checks intentionally inspect only hashes, schemas and artifact absence;
 # no prediction or benchmark metric is read or computed here.
 passed=all(x['status']=='PASS' for x in checks) and all(x['status']=='PASS' for x in hash_checks.values()) and not any(artifact_state.values())
 payload={'stage':10,'cycle_version':'stage10_v2','status':'PASS' if passed else 'BLOCKED','created_at_utc':datetime.now(timezone.utc).isoformat(),'preanalysis_manifest_path':str(manifest.relative_to(ROOT)).replace('\\','/'),'preanalysis_manifest_sha256':sha(manifest),'checks':checks,'hash_checks':hash_checks,'formal_artifacts_present_before_unseal':artifact_state,'test_labels_read_for_metrics_before_unseal':False,'test_predictions_read_before_unseal':False,'benchmark_metrics_computed_before_unseal':False,'test_tuning_before_unseal':False,'model_retrained_before_unseal':False,'locked_test_modified':'NO','stage11_started':'NO'}
 out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(payload,indent=2,ensure_ascii=False)); return 0 if passed else 1
if __name__=='__main__': raise SystemExit(main())
