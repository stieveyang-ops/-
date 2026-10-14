from __future__ import annotations
import argparse, json, time
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from aiz_rd.precedent import ReactionPrecedentIndex, RXNFPRuntime
ROOT=Path(__file__).resolve().parents[1]
def atomic_json(path: Path, payload: dict):
 fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
 try: tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,path)
 finally:
  if tmp.exists(): tmp.unlink()
def main()->int:
 ap=argparse.ArgumentParser(); ap.add_argument('--config',default=str(ROOT/'config/precedent.yml')); ap.add_argument('--queries',default=str(ROOT/'data/processed/reaction_steps_raw.parquet')); args=ap.parse_args(); report={'status':'BLOCKED','errors':[],'warnings':[]}
 try:
  md=pd.read_parquet(ROOT/'artifacts/reference_metadata.parquet'); idx=ReactionPrecedentIndex(ROOT/'artifacts/reference_rxnfp.npy',ROOT/'artifacts/reference_metadata.parquet',ROOT/'artifacts/reference_nn_index.joblib',RXNFPRuntime(),top_k=100)
  self_rows=md.head(min(10,len(md))); self_results=[]
  self_vecs=idx.runtime.embed_many(self_rows.reaction_smiles.tolist())
  self_vec_map={row.reaction_smiles:vec for row,vec in zip(self_rows.itertuples(index=False),self_vecs)}
  for row in self_rows.itertuples(index=False):
   qvec=self_vec_map[row.reaction_smiles]
   dep=idx.query_vector(qvec,row.reaction_hash,mode='deployment'); bench=idx.query_vector(qvec,row.reaction_hash,mode='benchmark')
   if not dep or dep[0]['reaction_hash']!=row.reaction_hash or dep[0]['similarity']<0.99999: raise RuntimeError('BLOCKED_BENCHMARK_SELF_MATCH: deployment self-query failed')
   if any(x['reaction_hash']==row.reaction_hash for x in bench): raise RuntimeError('BLOCKED_BENCHMARK_SELF_MATCH: benchmark returned exact hash')
   self_results.append({'reference_id':row.reference_id,'reaction_hash':row.reaction_hash,'deployment_top1':dep[0],'benchmark_top1':bench[0] if bench else None,'benchmark_effective_k':len(bench)})
  q=pd.read_parquet(args.queries).sort_values('step_id').head(20); smoke=[]; t0=time.perf_counter()
  all_queries=[row.reaction_smiles for row in q.itertuples(index=False)]
  all_queries.extend(self_rows.reaction_smiles.tolist())
  runtime=idx.runtime; vectors=runtime.embed_many(list(dict.fromkeys(all_queries))); vector_map={s:v for s,v in zip(dict.fromkeys(all_queries),vectors)}
  for row in q.itertuples(index=False):
   for mode in ('deployment','benchmark'):
    res=idx.query_vector(vector_map[row.reaction_smiles],row.reaction_hash,mode=mode); smoke.append({'step_id':row.step_id,'reaction_hash':row.reaction_hash,'mode':mode,'effective_k':len(res),'top1_reference_id':res[0]['reference_id'] if res else None,'top1_similarity':res[0]['similarity'] if res else None,'top1_reaction_smiles':res[0]['reaction_smiles'] if res else None,'exact_match_present':any(x['reaction_hash']==row.reaction_hash for x in res)})
    if any(not (0<=x['similarity']<=1) for x in res): raise RuntimeError('similarity outside [0,1]')
    if mode=='benchmark' and any(x['reaction_hash']==row.reaction_hash for x in res): raise RuntimeError('BLOCKED_BENCHMARK_SELF_MATCH')
  report.update({'status':'PASS','self_query_count':len(self_results),'self_queries':self_results,'stage2_query_count':len(q),'stage2_queries':smoke,'total_query_seconds':time.perf_counter()-t0,'mean_query_seconds':(time.perf_counter()-t0)/(2*len(q)) if len(q) else 0,'timestamp_utc':datetime.now(timezone.utc).isoformat()})
 except Exception as exc: report['errors'].append(f'{type(exc).__name__}: {exc}')
 atomic_json(ROOT/'reports/precedent_search_smoke_test.json', report); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
