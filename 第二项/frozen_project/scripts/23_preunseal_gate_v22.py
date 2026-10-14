"""Run and record Stage 10 v2.2 pre-unseal checks."""
from __future__ import annotations
import argparse, hashlib, json, subprocess
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
def run(cmd):
 st=datetime.now(timezone.utc); p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
 return {'command':' '.join(cmd),'started_at_utc':st.isoformat(),'finished_at_utc':datetime.now(timezone.utc).isoformat(),'exit_code':p.returncode,'stdout_tail':p.stdout[-4000:],'stderr_tail':p.stderr[-4000:],'status':'PASS' if p.returncode==0 else 'FAIL'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--manifest',default='reports/stage10_preanalysis_manifest_v22.json'); ap.add_argument('--output',default='reports/stage10_preunseal_test_report_v22.json'); a=ap.parse_args(); manifest=ROOT/a.manifest; out=ROOT/a.output
 if not manifest.exists(): raise RuntimeError('BLOCKED_STAGE10_V22_PREANALYSIS_MISSING')
 m=json.loads(manifest.read_text(encoding='utf-8')); tests=['tests/test_stage10_models.py','tests/test_stage10_metrics.py','tests/test_cluster_bootstrap.py','tests/test_ablation.py','tests/test_precedent_sensitivity.py','tests/test_scscore_sensitivity.py','tests/test_leakage_audit.py','tests/test_stage10_integrity.py','tests/test_stage10_v22_integrity.py']; checks=[run([r'E:\Anaconda\envs\aizynth\python.exe','-m','pytest','-q',*tests]),run([r'E:\Anaconda\envs\aizynth\python.exe','-m','pytest','-q']),run([r'E:\Anaconda\envs\aizynth\python.exe','scripts/12_leakage_audit.py'])]
 hashes={k:{'expected':m[k],'actual':sha(ROOT/p)} for k,p in {'locked_test_sha256':'data/splits/test_ids_locked.txt','stage8_model_sha256':'artifacts/difficulty_model.pkl','stage8_model_metadata_sha256':'artifacts/difficulty_model_metadata.json','stage9_ranking_sha256':'outputs/scored_routes.parquet'}.items()}
 for x in hashes.values(): x['status']='PASS' if x['expected']==x['actual'] else 'FAIL'
 outputs=['data/benchmark/stage10_benchmark_reactions_v22.parquet','outputs/stage10_locked_test_predictions_v22.parquet','reports/benchmark_results_v22.csv','reports/benchmark_results_v22.json','reports/bootstrap_metrics_v22.parquet','reports/model_pairwise_differences_v22.csv','reports/ablation_results_v22.csv','reports/ablation_results_v22.json','reports/precedent_sensitivity_results_v22.csv','reports/precedent_sensitivity_results_v22.json','artifacts/sc_delta_mean_ecdf_stage10_v22.npz','reports/scscore_sensitivity_results_v22.csv','reports/scscore_sensitivity_results_v22.json','reports/leakage_audit_v22.json','reports/stage10_manifest_v22.json']; present={p:(ROOT/p).exists() for p in outputs}
 passed=all(x['status']=='PASS' for x in checks) and all(x['status']=='PASS' for x in hashes.values()) and not any(present.values()); payload={'stage':10,'cycle_version':'stage10_v2.2','status':'PASS' if passed else 'BLOCKED','created_at_utc':datetime.now(timezone.utc).isoformat(),'preanalysis_manifest_path':str(manifest.relative_to(ROOT)).replace('\\','/'),'preanalysis_manifest_sha256':sha(manifest),'checks':checks,'hash_checks':hashes,'v22_formal_artifacts_present_before_unseal':present,'test_labels_read_for_metrics_before_unseal':False,'test_predictions_read_before_unseal':False,'benchmark_metrics_computed_before_unseal':False,'test_tuning_before_unseal':False,'model_retrained_before_unseal':False,'locked_test_modified':'NO','stage11_started':'NO'}; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(payload,indent=2,ensure_ascii=False)); return 0 if passed else 1
if __name__=='__main__': raise SystemExit(main())
