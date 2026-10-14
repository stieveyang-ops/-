"""Build Stage 5 reference ΔSC ECDF under the approved product rule."""
from __future__ import annotations
import argparse, hashlib, json, math, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from aizynthfinder.utils.sc_score import SCScore
from aiz_rd.sc_feature import compute_reference_delta_sc

ROOT=Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
def atomic_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
    try: tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,path)
    finally:
        if tmp.exists(): tmp.unlink()
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--reference',default=str(ROOT/'data/reference/reference_reactions_clean.parquet')); ap.add_argument('--environment-check',default=str(ROOT/'reports/environment_check.json')); ap.add_argument('--config',default=str(ROOT/'config/stage5_features.yml')); ap.add_argument('--output',default=str(ROOT/'artifacts/sc_delta_ecdf.npz')); ap.add_argument('--audit-output',default=str(ROOT/'data/reference/reference_sc_ecdf_audit.parquet')); args=ap.parse_args(); report={'status':'BLOCKED','errors':[],'warnings':[]}
    try:
        env=json.loads(Path(args.environment_check).read_text(encoding='utf-8')); model_path=Path(env['scscore']['model_path']); model_sha=sha(model_path)
        if env.get('scscore',{}).get('status')!='PASS' or model_sha!=env['scscore']['sha256'].upper(): raise RuntimeError('BLOCKED_SCScore_MODEL_DRIFT')
        ref=pd.read_parquet(args.reference); model=SCScore(str(model_path)); rows=[]; valid=[]
        for row in ref.itertuples(index=False):
            result=compute_reference_delta_sc(str(row.reaction_smiles),model); item={'reference_id':str(row.reference_id),'reaction_hash':str(row.reaction_hash),'source':str(row.source),'duplicate_count':int(row.duplicate_count),'reaction_smiles':str(row.reaction_smiles),'product_component_count':int(result.product_component_count),'valid_for_sc_ecdf':bool(result.valid_for_ecdf),'sc_product':result.sc_product,'sc_precursor_max':result.sc_precursor_max,'delta_sc':result.delta_sc,'exclusion_reason':result.exclusion_reason,'error_type':result.error_type,'error_message':result.error_message}; rows.append(item)
            if result.valid_for_ecdf: valid.append(float(result.delta_sc))
        if not valid: raise RuntimeError('BLOCKED_ECDF_NO_VALID_REFERENCE')
        values=np.sort(np.asarray(valid,dtype=np.float64));
        if not np.isfinite(values).all() or np.any(values[1:]<values[:-1]): raise RuntimeError('BLOCKED_ECDF_INVALID_VALUES')
        out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f'.{out.name}.',suffix='.tmp',dir=str(out.parent)); os.close(fd); tmp=Path(tmp)
        try: np.savez(tmp,delta_sc_sorted=values,n_reference_valid=np.int64(len(values)),reference_corpus_sha256=sha(Path(args.reference)),scscore_model_sha256=model_sha,algorithm_version='ecdf-right-v1',product_rule_version='single_connected_product_only_v1'); os.replace(Path(str(tmp)+'.npz') if Path(str(tmp)+'.npz').exists() else tmp,out)
        finally:
            if tmp.exists(): tmp.unlink()
        audit=pd.DataFrame(rows); audit_path=Path(args.audit_output); audit_path.parent.mkdir(parents=True,exist_ok=True); audit.to_parquet(audit_path,index=False,engine='pyarrow',compression='zstd')
        report.update({'status':'PASS','product_rule_version':'single_connected_product_only_v1','n_reference_total':len(ref),'n_reference_valid':len(values),'n_reference_invalid':len(ref)-len(values),'invalid_reason_counts':audit.loc[~audit.valid_for_sc_ecdf,'exclusion_reason'].fillna('unknown').value_counts().to_dict(),'invalid_duplicate_count_sum':int(audit.loc[~audit.valid_for_sc_ecdf,'duplicate_count'].sum()),'delta_min':float(values.min()),'delta_median':float(np.median(values)),'delta_max':float(values.max()),'reference_corpus_sha256':sha(Path(args.reference)),'scscore_model_sha256':model_sha,'ecdf_artifact_sha256':sha(out),'audit_output_sha256':sha(audit_path),'timestamp_utc':datetime.now(timezone.utc).isoformat()})
    except Exception as exc: report['errors'].append(f'{type(exc).__name__}: {exc}')
    atomic_json(ROOT/'reports/stage5_ecdf_build_report.json',report); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
