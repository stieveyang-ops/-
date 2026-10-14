"""Create the one-time locked-test unseal receipt."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--preanalysis',default='reports/stage10_preanalysis_manifest.json'); ap.add_argument('--output',default='reports/test_unseal_receipt.json'); a=ap.parse_args(); pre=ROOT/a.preanalysis; out=ROOT/a.output
 if not pre.exists(): raise RuntimeError('BLOCKED_PREANALYSIS_MISSING')
 payload={"stage":10,"status":"UNSEALED_ONCE","unseal_time_utc":datetime.now(timezone.utc).isoformat(),"test_ids_sha256":sha(ROOT/'data/splits/test_ids_locked.txt'),"preanalysis_manifest_sha256":sha(pre),"git_commit":None}
 if out.exists():
  old=json.loads(out.read_text(encoding='utf-8'))
  if old.get('test_ids_sha256')!=payload['test_ids_sha256'] or old.get('preanalysis_manifest_sha256')!=payload['preanalysis_manifest_sha256']: raise RuntimeError('BLOCKED_UNSEAL_RECEIPT_DRIFT')
  print(json.dumps(old,indent=2)); return 0
 out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(payload,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
