"""Apply a frozen reference-only right-continuous ΔSC ECDF to Stage 3 queries."""
from __future__ import annotations
import argparse, hashlib, json, math, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from aiz_rd.sc_feature import ecdf_right_continuous
ROOT=Path(__file__).resolve().parents[1]
OUTPUT_COLUMNS=['target_id','route_id','step_id','reaction_hash','reaction_smiles','sc_product','sc_precursor_max','delta_sc','d_sc','ecdf_n_reference','ecdf_algorithm','reference_corpus_sha256','scscore_model_sha256','ecdf_artifact_sha256']
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
def atomic_parquet(df,path):
 path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
 try: df.to_parquet(tmp,index=False,engine='pyarrow',compression='zstd'); os.replace(tmp,path)
 finally:
  if tmp.exists(): tmp.unlink()
def atomic_json(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{path.name}.',suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
 try: tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,path)
 finally:
  if tmp.exists(): tmp.unlink()
def main()->int:
 ap=argparse.ArgumentParser(); ap.add_argument('--input',default=str(ROOT/'data/processed/reaction_sc_raw.parquet')); ap.add_argument('--steps',default=str(ROOT/'data/processed/reaction_steps_raw.parquet')); ap.add_argument('--ecdf',default=str(ROOT/'artifacts/sc_delta_ecdf.npz')); ap.add_argument('--output',default=str(ROOT/'data/processed/reaction_sc_normalized.parquet')); args=ap.parse_args(); report={'status':'BLOCKED','errors':[],'warnings':[]}
 try:
  src=pd.read_parquet(args.input); steps=pd.read_parquet(args.steps); z=np.load(args.ecdf,allow_pickle=False); values=np.asarray(z['delta_sc_sorted'],dtype=np.float64); n=int(z['n_reference_valid']); ref_sha=str(z['reference_corpus_sha256'].item() if getattr(z['reference_corpus_sha256'],'shape',()) else z['reference_corpus_sha256']); model_sha=str(z['scscore_model_sha256'].item() if getattr(z['scscore_model_sha256'],'shape',()) else z['scscore_model_sha256']); art_sha=sha(Path(args.ecdf))
  if not src[['target_id','route_id','step_id','reaction_hash']].reset_index(drop=True).equals(steps[['target_id','route_id','step_id','reaction_hash']].reset_index(drop=True)): raise RuntimeError('BLOCKED_QUERY_OR_REFERENCE_ALIGNMENT')
  if n!=len(values) or n<=0 or not np.isfinite(values).all() or np.any(values[1:]<values[:-1]): raise RuntimeError('BLOCKED_ECDF_INVALID_VALUES')
  rows=[]
  for row,step in zip(src.itertuples(index=False),steps.itertuples(index=False)):
   d=float(row.delta_sc); dsc=ecdf_right_continuous(values,d); rows.append({'target_id':str(row.target_id),'route_id':str(row.route_id),'step_id':str(row.step_id),'reaction_hash':str(row.reaction_hash),'reaction_smiles':str(step.reaction_smiles),'sc_product':float(row.sc_product),'sc_precursor_max':float(row.sc_precursor_max),'delta_sc':d,'d_sc':dsc,'ecdf_n_reference':n,'ecdf_algorithm':'ecdf-right-v1','reference_corpus_sha256':ref_sha,'scscore_model_sha256':model_sha,'ecdf_artifact_sha256':art_sha})
  out=pd.DataFrame(rows,columns=OUTPUT_COLUMNS); atomic_parquet(out,Path(args.output)); report.update({'status':'PASS','n_queries':len(out),'d_sc_min':float(out.d_sc.min()),'d_sc_max':float(out.d_sc.max()),'ecdf_n_reference':n,'ecdf_algorithm':'ecdf-right-v1','reference_corpus_sha256':ref_sha,'scscore_model_sha256':model_sha,'ecdf_artifact_sha256':art_sha,'output_sha256':sha(Path(args.output)),'timestamp_utc':datetime.now(timezone.utc).isoformat()})
 except Exception as exc: report['errors'].append(f'{type(exc).__name__}: {exc}')
 atomic_json(ROOT/'reports/stage5_sc_apply_report.json',report); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
