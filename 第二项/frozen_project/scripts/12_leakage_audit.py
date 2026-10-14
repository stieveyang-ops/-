"""Stage 10 pre/final leakage audit on frozen artifacts."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pandas as pd
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from aiz_rd.leakage import audit_leakage
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--output',default='reports/leakage_audit.json'); a=ap.parse_args()
 feat=pd.read_parquet(ROOT/'data/processed/reaction_features.parquet')
 labels=pd.read_parquet(ROOT/'data/labels/final_expert_labels.parquet')
 split=pd.read_parquet(ROOT/'data/splits/split_assignments.parquet')
 ref=pd.read_parquet(ROOT/'artifacts/reference_metadata.parquet')
 # Unique labeled benchmark candidate: deterministic first feature row per reaction.
 b=feat[feat.reaction_hash.isin(labels.reaction_hash)].sort_values(['reaction_hash','route_id','step_id'],kind='mergesort').drop_duplicates('reaction_hash')
 b=b.merge(labels[['reaction_hash','expert_label']],on='reaction_hash',how='left',validate='one_to_one')
 report=audit_leakage(b,split,ref)
 report.update({'stage':10,'status': 'PASS' if report['status']=='PASS' else 'BLOCKED','reference_metadata_sha256':sha(ROOT/'artifacts/reference_metadata.parquet'),'benchmark_reaction_hashes':int(len(b)),'timestamp_utc':pd.Timestamp.utcnow().isoformat()})
 out=ROOT/a.output; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
