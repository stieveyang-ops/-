"""Create the versioned, one-time Stage 10 v2 unseal receipt."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest().upper()
def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--manifest',default='reports/stage10_preanalysis_manifest_v2.json'); ap.add_argument('--preunseal-report',default='reports/stage10_preunseal_test_report_v2.json'); ap.add_argument('--output',default='reports/stage10_unseal_receipt_v2.json'); a=ap.parse_args()
    manifest=ROOT/a.manifest; report=ROOT/a.preunseal_report; out=ROOT/a.output
    if not manifest.exists() or not report.exists(): raise RuntimeError('BLOCKED_STAGE10_PREUNSEAL_GATE_NOT_SATISFIED')
    m=json.loads(manifest.read_text(encoding='utf-8')); r=json.loads(report.read_text(encoding='utf-8'))
    if r.get('status')!='PASS': raise RuntimeError('BLOCKED_STAGE10_PREUNSEAL_GATE_NOT_SATISFIED')
    pre_finish=max((x.get('finished_at_utc','') for x in r.get('checks',[])), default='')
    if not pre_finish: raise RuntimeError('BLOCKED_STAGE10_PREUNSEAL_GATE_NOT_SATISFIED')
    pre_time=datetime.fromisoformat(pre_finish.replace('Z','+00:00'))
    receipt_time=datetime.now(timezone.utc)
    if receipt_time <= pre_time: raise RuntimeError('BLOCKED_STAGE10_PREUNSEAL_GATE_NOT_SATISFIED')
    old=ROOT/'reports/test_unseal_receipt.json'
    payload={'stage':10,'cycle_version':'stage10_v2','status':'UNSEALED_ONCE','preanalysis_manifest_path':str(manifest.relative_to(ROOT)).replace('\\','/'),'preanalysis_manifest_sha256':sha(manifest),'locked_test_path':'data/splits/test_ids_locked.txt','locked_test_sha256':sha(ROOT/'data/splits/test_ids_locked.txt'),'preunseal_test_report_path':str(report.relative_to(ROOT)).replace('\\','/'),'preunseal_test_report_sha256':sha(report),'preunseal_test_completion_timestamp':pre_finish,'receipt_creation_timestamp':receipt_time.isoformat(),'temporal_ordering_verified':True,'old_receipt_path':'reports/test_unseal_receipt.json','old_receipt_sha256':sha(old) if old.exists() else None,'old_receipt_preserved':True,'locked_test_modified':'NO','stage11_started':'NO'}
    if out.exists():
        old_payload=json.loads(out.read_text(encoding='utf-8'))
        for k in ['cycle_version','preanalysis_manifest_sha256','locked_test_sha256','preunseal_test_report_sha256','temporal_ordering_verified']:
            if old_payload.get(k)!=payload.get(k): raise RuntimeError('BLOCKED_STAGE10_V2_UNSEAL_RECEIPT_DRIFT')
        print(json.dumps(old_payload,indent=2,ensure_ascii=False)); return 0
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); print(json.dumps(payload,indent=2,ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
