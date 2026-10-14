"""Compute Stage 5 precedent scores using the full Stage 4 reference corpus."""
from __future__ import annotations

import argparse, hashlib, json, math, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from aiz_rd.precedent import ReactionPrecedentIndex, RXNFPRuntime

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_COLUMNS = ["target_id", "route_id", "step_id", "reaction_hash", "reaction_smiles", "search_mode", "tau", "n0", "s_max", "n_analog", "p_prec", "d_prec", "n_exact_hash_excluded", "nearest_reference_id", "nearest_reference_hash", "nearest_reference_similarity", "reference_corpus_sha256", "rxnfp_artifact_sha256"]

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest().upper()
def atomic_parquet(df, path):
    path.parent.mkdir(parents=True, exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
    try: df.to_parquet(tmp,index=False,engine='pyarrow',compression='zstd'); os.replace(tmp,path)
    finally:
        if tmp.exists(): tmp.unlink()
def atomic_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
    try: tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,path)
    finally:
        if tmp.exists(): tmp.unlink()

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--queries',default=str(ROOT/'data/processed/reaction_steps_raw.parquet')); ap.add_argument('--reference-embeddings',default=str(ROOT/'artifacts/reference_rxnfp.npy')); ap.add_argument('--reference-metadata',default=str(ROOT/'artifacts/reference_metadata.parquet')); ap.add_argument('--reference-corpus',default=str(ROOT/'data/reference/reference_reactions_clean.parquet')); ap.add_argument('--config',default=str(ROOT/'config/stage5_features.yml')); ap.add_argument('--mode',choices=['deployment','benchmark'],default=None); ap.add_argument('--output',default=str(ROOT/'data/processed/reaction_precedent.parquet')); ap.add_argument('--force',action='store_true'); args=ap.parse_args()
    report={'status':'BLOCKED','errors':[],'warnings':[]}
    try:
        import yaml
        cfg=yaml.safe_load(Path(args.config).read_text(encoding='utf-8')); pcfg=cfg['precedent']; mode=args.mode or pcfg['mode']; tau=float(pcfg['tau']); n0=float(pcfg['n0'])
        q=pd.read_parquet(args.queries); ref=pd.read_parquet(args.reference_metadata); emb=np.load(args.reference_embeddings,mmap_mode='r')
        if len(q)==0 or q.step_id.duplicated().any() or len(ref)!=len(emb) or ref.reaction_hash.duplicated().any() or emb.shape!=(len(ref),256): raise RuntimeError('BLOCKED_QUERY_OR_REFERENCE_ALIGNMENT')
        if mode=='benchmark' and not q.reaction_hash.astype(str).map(lambda x: isinstance(x,str)).all(): raise RuntimeError('BLOCKED_BENCHMARK_HASH_EXCLUSION')
        idx=ReactionPrecedentIndex(args.reference_embeddings,args.reference_metadata,ROOT/'artifacts/reference_nn_index.joblib',RXNFPRuntime(),top_k=int(pcfg.get('top_k_for_reporting',10)))
        vecs=idx.runtime.embed_many(q.reaction_smiles.astype(str).tolist()); rows=[]
        for row,vec in zip(q.itertuples(index=False),vecs):
            score=idx.full_corpus_score(vec,str(row.reaction_hash),mode=mode,tau=tau,n0=n0)
            rows.append({'target_id':str(row.target_id),'route_id':str(row.route_id),'step_id':str(row.step_id),'reaction_hash':str(row.reaction_hash),'reaction_smiles':str(row.reaction_smiles),'search_mode':score.search_mode,'tau':score.tau,'n0':score.n0,'s_max':score.s_max,'n_analog':score.n_analog,'p_prec':score.p_prec,'d_prec':score.d_prec,'n_exact_hash_excluded':score.n_exact_hash_excluded,'nearest_reference_id':score.nearest_reference_id,'nearest_reference_hash':score.nearest_reference_hash,'nearest_reference_similarity':score.nearest_reference_similarity,'reference_corpus_sha256':sha(Path(args.reference_corpus)),'rxnfp_artifact_sha256':sha(Path(args.reference_embeddings))})
        out=pd.DataFrame(rows,columns=OUTPUT_COLUMNS); atomic_parquet(out,Path(args.output));
        vals=out[['s_max','p_prec','d_prec']].to_numpy(float)
        report.update({'status':'PASS','n_queries':len(out),'mode':mode,'tau':tau,'n0':n0,'s_max_min':float(out.s_max.min()),'s_max_max':float(out.s_max.max()),'n_analog_min':int(out.n_analog.min()),'n_analog_max':int(out.n_analog.max()),'p_prec_min':float(out.p_prec.min()),'p_prec_max':float(out.p_prec.max()),'d_prec_min':float(out.d_prec.min()),'d_prec_max':float(out.d_prec.max()),'n_exact_hash_excluded':int((out.search_mode=='benchmark').sum()),'reference_corpus_sha256':sha(Path(args.reference_corpus)),'rxnfp_artifact_sha256':sha(Path(args.reference_embeddings)),'output_sha256':sha(Path(args.output)),'timestamp_utc':datetime.now(timezone.utc).isoformat()})
    except Exception as exc: report['errors'].append(f'{type(exc).__name__}: {exc}')
    atomic_json(ROOT/'reports/stage5_precedent_report.json',report); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
