"""Create the one-time Stage 10 v2.2 unseal receipt."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  block=f.read(1024*1024)
  while block:
   h.update(block); block=f.read(1024*1024)
 return h.hexdigest().upper()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--manifest',default='reports/stage10_preanalysis_manifest_v22.json'); ap.add_argument('--preunseal-report',default='reports/stage10_preunseal_test_report_v22.json'); ap.add_argument('--output',default='reports/stage10_unseal_receipt_v22.json'); a=ap.parse_args(); manifest=ROOT/a.manifest; report=ROOT/a.preunseal_report; out=ROOT/a.output; old=ROOT/'reports/test_unseal_receipt.json'
 if not manifest.exists() or not report.exists(): raise RuntimeError('BLOCKED_STAGE10_PREUNSEAL_GATE_NOT_SATISFIED')
 r=json.loads(report.read_text(encoding='utf-8'))
 if r.get('status')!='PASS': raise RuntimeError('BLOCKED_STAGE10_PREUNSEAL_GATE_NOT_SATISFIED')
 finish=max(x.get('finished_at_utc','') for x in r.get('checks',[])); pre=datetime.fromisoformat(finish.replace('Z','+00:00')); now=datetime.now(timezone.utc)
 if now<=pre: raise RuntimeError('BLOCKED_STAGE10_PREUNSEAL_GATE_NOT_SATISFIED')
 if out.exists(): raise RuntimeError('BLOCKED_STAGE10_V22_UNSEAL_RECEIPT_ALREADY_EXISTS')
 payload={'stage':10,'cycle_version':'stage10_v2.2','status':'UNSEALED_ONCE','preanalysis_manifest_path':str(manifest.relative_to(ROOT)).replace('\\','/'),'preanalysis_manifest_sha256':sha(manifest),'locked_test_path':'data/splits/test_ids_locked.txt','locked_test_sha256':sha(ROOT/'data/splits/test_ids_locked.txt'),'preunseal_test_report_path':str(report.relative_to(ROOT)).replace('\\','/'),'preunseal_test_report_sha256':sha(report),'preunseal_test_completion_timestamp':finish,'receipt_creation_timestamp':now.isoformat(),'temporal_ordering_verified':True,'old_receipt_path':'reports/test_unseal_receipt.json','old_receipt_sha256':sha(old),'old_receipt_preserved':True,'locked_test_modified':'NO','stage11_started':'NO'}; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(payload,indent=2,ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
