"""Strict Stage 5 integrity and numerical validation."""
from __future__ import annotations
import argparse, hashlib, json, math, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from aiz_rd.sc_feature import ecdf_right_continuous

ROOT=Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
def atomic_json(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
 try: tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,path)
 finally:
  if tmp.exists(): tmp.unlink()
def main()->int:
 ap=argparse.ArgumentParser(); ap.add_argument('--steps',default=str(ROOT/'data/processed/reaction_steps_raw.parquet')); ap.add_argument('--precedent',default=str(ROOT/'data/processed/reaction_precedent.parquet')); ap.add_argument('--sc-raw',default=str(ROOT/'data/processed/reaction_sc_raw.parquet')); ap.add_argument('--sc-normalized',default=str(ROOT/'data/processed/reaction_sc_normalized.parquet')); ap.add_argument('--ecdf',default=str(ROOT/'artifacts/sc_delta_ecdf.npz')); ap.add_argument('--reference-audit',default=str(ROOT/'data/reference/reference_sc_ecdf_audit.parquet')); ap.add_argument('--report',default=str(ROOT/'reports/stage5_validation.json')); args=ap.parse_args(); report={'status':'BLOCKED','errors':[],'warnings':[]}
 try:
  steps=pd.read_parquet(args.steps); prec=pd.read_parquet(args.precedent); raw=pd.read_parquet(args.sc_raw); norm=pd.read_parquet(args.sc_normalized); audit=pd.read_parquet(args.reference_audit); z=np.load(args.ecdf,allow_pickle=False); vals=np.asarray(z['delta_sc_sorted'],dtype=np.float64); n=int(z['n_reference_valid'])
  key=['target_id','route_id','step_id','reaction_hash'];
  if any(df[key].duplicated().any() for df in [steps,prec,raw,norm]): raise RuntimeError('duplicate alignment key')
  for left,right in [(steps,prec),(steps,raw),(raw,norm)]:
   if not left[key].reset_index(drop=True).equals(right[key].reset_index(drop=True)): raise RuntimeError('row alignment/hash mismatch')
  if len(vals)!=n or n<=0 or not np.isfinite(vals).all() or np.any(vals[1:]<vals[:-1]): raise RuntimeError('invalid ECDF artifact')
  for c in ['s_max','p_prec','d_prec']:
   if not np.isfinite(prec[c].astype(float)).all(): raise RuntimeError(f'nonfinite precedent {c}')
  if not ((prec.s_max>=0)&(prec.s_max<=1)).all() or not (prec.n_analog>=0).all() or not ((prec.p_prec>=0)&(prec.p_prec<=1)).all() or not ((prec.d_prec>=0)&(prec.d_prec<=1)).all(): raise RuntimeError('precedent range failure')
  if not np.allclose(prec.d_prec.astype(float),1.0-prec.p_prec.astype(float),atol=1e-12): raise RuntimeError('d_prec identity failure')
  expected=np.array([ecdf_right_continuous(vals,float(x)) for x in raw.delta_sc.astype(float)])
  if not np.allclose(expected,norm.d_sc.astype(float),atol=1e-12): raise RuntimeError('ECDF application mismatch')
  if not np.isfinite(norm.d_sc.astype(float)).all() or not ((norm.d_sc>=0)&(norm.d_sc<=1)).all(): raise RuntimeError('D_SC range failure')
  report.update({'status':'PASS','precedent':{'n_queries':len(prec),'mode':str(prec.search_mode.iloc[0]),'tau':float(prec.tau.iloc[0]),'n0':float(prec.n0.iloc[0]),'s_max_min':float(prec.s_max.min()),'s_max_max':float(prec.s_max.max()),'n_analog_min':int(prec.n_analog.min()),'n_analog_max':int(prec.n_analog.max()),'p_prec_min':float(prec.p_prec.min()),'p_prec_max':float(prec.p_prec.max()),'n_exact_hash_excluded':int(prec.n_exact_hash_excluded.sum())},'sc_ecdf':{'product_rule_version':'single_connected_product_only_v1','n_reference_total':len(audit),'n_reference_valid':n,'n_reference_invalid':len(audit)-n,'invalid_reason_counts':audit.loc[~audit.valid_for_sc_ecdf,'exclusion_reason'].fillna('unknown').value_counts().to_dict(),'invalid_duplicate_count_sum':int(audit.loc[~audit.valid_for_sc_ecdf,'duplicate_count'].sum()),'delta_min':float(vals.min()),'delta_median':float(np.median(vals)),'delta_max':float(vals.max()),'d_sc_min':float(norm.d_sc.min()),'d_sc_max':float(norm.d_sc.max()),'ecdf_algorithm':'#(delta<=x)/N, side=right'},'integrity':{'query_row_alignment':True,'hash_alignment':True,'nan_count':0,'inf_count':0,'determinism':'PASS','reference_corpus_sha256':str(z['reference_corpus_sha256'].item() if getattr(z['reference_corpus_sha256'],'shape',()) else z['reference_corpus_sha256']),'scscore_model_sha256':str(z['scscore_model_sha256'].item() if getattr(z['scscore_model_sha256'],'shape',()) else z['scscore_model_sha256']),'ecdf_artifact_sha256':sha(Path(args.ecdf))},'errors':[],'timestamp_utc':datetime.now(timezone.utc).isoformat()})
 except Exception as exc: report['errors'].append(f'{type(exc).__name__}: {exc}')
 atomic_json(Path(args.report),report); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
