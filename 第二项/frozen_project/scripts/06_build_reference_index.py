from __future__ import annotations
import argparse, hashlib, json, os, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
import joblib, numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def sha256(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
def atomic_json(path, payload):
 fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
 try: tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,path)
 finally:
  if tmp.exists(): tmp.unlink()
def main()->int:
 ap=argparse.ArgumentParser(); ap.add_argument('--config',default=str(ROOT/'config/precedent.yml')); args=ap.parse_args(); report={'status':'BLOCKED','errors':[],'warnings':[]}
 try:
  emb=ROOT/'artifacts/reference_rxnfp.npy'; meta=ROOT/'artifacts/reference_metadata.parquet'; out=ROOT/'artifacts/reference_nn_index.joblib'
  arr=np.load(emb); md=pd.read_parquet(meta)
  if arr.shape!=(len(md),256) or md.embedding_row.tolist()!=list(range(len(md))) or not np.isfinite(arr).all(): raise RuntimeError('BLOCKED_EMBEDDING_METADATA_MISALIGNMENT')
  from sklearn.neighbors import NearestNeighbors
  t0=time.perf_counter(); index=NearestNeighbors(metric='cosine',algorithm='brute'); index.fit(arr)
  out.parent.mkdir(exist_ok=True); fd,tmp=tempfile.mkstemp(prefix='reference_nn_index.',suffix='.tmp',dir=str(out.parent)); os.close(fd); tmp=Path(tmp)
  try:
   joblib.dump(index,tmp); reloaded=joblib.load(tmp); d,i=reloaded.kneighbors(arr[:1],n_neighbors=1)
   if not np.isfinite(d).all() or i.shape!=(1,1): raise RuntimeError('BLOCKED_INDEX_BUILD')
   os.replace(tmp,out)
  finally:
   if tmp.exists(): tmp.unlink()
  report.update({'status':'PASS','backend':'sklearn','metric':'cosine','algorithm':'brute','n_embeddings':len(md),'embedding_sha256':sha256(emb),'metadata_sha256':sha256(meta),'index_sha256':sha256(out),'build_elapsed_seconds':time.perf_counter()-t0,'timestamp_utc':datetime.now(timezone.utc).isoformat()})
 except Exception as exc: report['errors'].append(f'{type(exc).__name__}: {exc}')
 atomic_json(ROOT/'reports/reference_index_report.json', report); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
