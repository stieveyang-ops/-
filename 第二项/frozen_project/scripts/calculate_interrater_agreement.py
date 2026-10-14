"""Calculate agreement before adjudication."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'src') not in sys.path: sys.path.insert(0,str(ROOT/'src'))
from aiz_rd.annotation import agreement_report, atomic_write_json
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--annotations',required=True); ap.add_argument('--output',required=True); a=ap.parse_args(); r=agreement_report(pd.read_parquet(Path(a.annotations).resolve())); atomic_write_json(r,Path(a.output).resolve()); print(json.dumps(r,indent=2,ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
