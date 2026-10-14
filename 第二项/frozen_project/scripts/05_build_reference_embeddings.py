from __future__ import annotations
import argparse, hashlib, json, os, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def sha256(p: Path): return hashlib.sha256(p.read_bytes()).hexdigest().upper()
def atomic_json(path: Path, payload: dict):
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)); os.close(fd); tmp_path = Path(tmp)
    try:
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8'); os.replace(tmp_path, path)
    finally:
        if tmp_path.exists(): tmp_path.unlink()
def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default=str(ROOT/'config/precedent.yml')); ap.add_argument('--clean-csv',default=None,help='Temporary CSV prepared by the main environment when isolated RXNFP runtime lacks pyarrow'); ap.add_argument('--metadata-csv',default=None,help='Metadata CSV output for isolated runtime without pyarrow'); args=ap.parse_args()
    import yaml
    cfg=yaml.safe_load(Path(args.config).read_text(encoding='utf-8')); rcfg=cfg['rxnfp']
    clean=ROOT/'data/reference/reference_reactions_clean.parquet'; out_npy=ROOT/'artifacts/reference_rxnfp.npy'; out_meta=ROOT/'artifacts/reference_metadata.parquet'; report_path=ROOT/'reports/rxnfp_build_report.json'
    report={'status':'BLOCKED','errors':[],'warnings':[]}
    try:
        if not clean.is_file(): raise RuntimeError('BLOCKED_REFERENCE_FILE_UNREADABLE: clean corpus missing')
        if args.clean_csv:
            df=pd.read_csv(args.clean_csv,dtype={'reference_id':str,'reaction_smiles':str,'reaction_hash':str,'source':str,'source_record_ids_json':str,'duplicate_count':'int64'}).sort_values('reaction_hash').reset_index(drop=True)
        else:
            df=pd.read_parquet(clean).sort_values('reaction_hash').reset_index(drop=True)
        if len(df)==0 or not df.reaction_hash.is_unique: raise RuntimeError('BLOCKED_EMBEDDING_METADATA_MISALIGNMENT: clean corpus empty/nonunique')
        from rxnfp.transformer_fingerprints import RXNBERTFingerprintGenerator,get_default_model_and_tokenizer
        model,tokenizer=get_default_model_and_tokenizer(model='bert_ft',force_no_cuda=True)
        generator=RXNBERTFingerprintGenerator(model,tokenizer,force_no_cuda=True)
        batch_size=int(rcfg.get('batch_size',32)); t0=time.perf_counter(); parts=[]
        for start in range(0,len(df),batch_size):
            parts.append(np.asarray(generator.convert_batch(df.reaction_smiles.iloc[start:start+batch_size].tolist()),dtype=np.float32))
        arr=np.vstack(parts).astype(np.float32,copy=False)
        if arr.shape != (len(df),256): raise RuntimeError(f'BLOCKED_RXNFP_DIMENSION_MISMATCH: {arr.shape}')
        if not np.isfinite(arr).all(): raise RuntimeError('BLOCKED_NONFINITE_EMBEDDING')
        norms=np.linalg.norm(arr,axis=1,keepdims=True)
        if np.any(norms<=0): raise RuntimeError('BLOCKED_ZERO_EMBEDDING')
        arr=(arr/norms).astype(np.float32)
        if not np.allclose(np.linalg.norm(arr,axis=1),1.0,atol=1e-5): raise RuntimeError('BLOCKED_EMBEDDING_NORMALIZATION')
        meta=df[['reference_id','reaction_hash','reaction_smiles','source','duplicate_count']].copy(); meta.insert(0,'embedding_row',np.arange(len(meta),dtype=np.int64))
        if not meta.reaction_hash.is_unique or not meta.reference_id.is_unique: raise RuntimeError('BLOCKED_EMBEDDING_METADATA_MISALIGNMENT')
        out_npy.parent.mkdir(exist_ok=True); out_meta.parent.mkdir(exist_ok=True)
        fd,tmpn=tempfile.mkstemp(prefix='reference_rxnfp.',suffix='.tmp.npy',dir=str(out_npy.parent)); os.close(fd); tmpn=Path(tmpn)
        fd,tmpm=tempfile.mkstemp(prefix='reference_metadata.',suffix='.tmp.parquet',dir=str(out_meta.parent)); os.close(fd); tmpm=Path(tmpm)
        try:
            np.save(tmpn,arr)
            if args.metadata_csv:
                metadata_csv = Path(args.metadata_csv); metadata_csv.parent.mkdir(parents=True, exist_ok=True)
                meta.to_csv(metadata_csv, index=False, encoding='utf-8')
                chk=np.load(tmpn)
                if chk.shape != (len(meta),256) or meta.embedding_row.tolist()!=list(range(len(meta))): raise RuntimeError('BLOCKED_EMBEDDING_METADATA_MISALIGNMENT')
                os.replace(tmpn,out_npy)
            else:
                meta.to_parquet(tmpm,index=False,engine='pyarrow',compression='zstd')
                chk=np.load(tmpn); chkmeta=pd.read_parquet(tmpm)
                if chk.shape != (len(chkmeta),256) or chkmeta.embedding_row.tolist()!=list(range(len(chkmeta))): raise RuntimeError('BLOCKED_EMBEDDING_METADATA_MISALIGNMENT')
                os.replace(tmpn,out_npy); os.replace(tmpm,out_meta)
        finally:
            for p in (tmpn,tmpm):
                if p.exists(): p.unlink()
        elapsed=time.perf_counter()-t0
        repeat=np.asarray(generator.convert_batch([df.reaction_smiles.iloc[0],df.reaction_smiles.iloc[0]]),dtype=np.float32)
        repeat=(repeat/np.linalg.norm(repeat,axis=1,keepdims=True)).astype(np.float32)
        report.update({'status':'PASS','rxnfp_package_version':'0.1.0','transformers_version':__import__('importlib.metadata',fromlist=['version']).version('transformers'),'torch_version':__import__('importlib.metadata',fromlist=['version']).version('torch'),'model_name':'bert_ft','device':'cpu','dimension':256,'dtype':'float32','l2_normalized':True,'batch_size_requested':batch_size,'batch_size_actual':batch_size,'n_embeddings':len(df),'embedding_shape':[len(df),256],'reference_clean_sha256':sha256(clean) if clean.is_file() else None,'embedding_npy_sha256':sha256(out_npy),'metadata_sha256':sha256(out_meta) if out_meta.exists() else None,'metadata_csv':str(args.metadata_csv) if args.metadata_csv else None,'model_files':[],'tokenizer_vocab_sha256':None,'tokenizer_vocab_note':'RXNFP package-managed bert_ft resources; no standalone vocabulary path was exposed.','repeatability_max_abs_diff':float(np.max(np.abs(repeat[0]-repeat[1]))),'build_elapsed_seconds':elapsed,'interpreter':str(Path(__file__).resolve().parents[1]/'.conda-rxnfp/python.exe'),'timestamp_utc':datetime.now(timezone.utc).isoformat()})
    except Exception as exc: report['errors'].append(f'{type(exc).__name__}: {exc}')
    report_path.parent.mkdir(exist_ok=True); atomic_json(report_path, report); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
