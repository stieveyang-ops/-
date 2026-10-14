"""Strictly validate returned expert files; never auto-resolve disagreement."""
from __future__ import annotations
import argparse, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path: sys.path.insert(0, str(ROOT / "src"))
from aiz_rd.annotation import (AnnotationValidationError, atomic_write_csv,
    atomic_write_json, atomic_write_parquet, agreement_report,
    build_adjudication_required, sha256, validate_expert_file)

def expert_args(values):
    out={}
    for item in values:
        if '=' not in item: raise AnnotationValidationError(f"expert must be E01=path: {item}")
        eid,path=item.split('=',1)
        if eid in out or not eid.startswith('E'): raise AnnotationValidationError(f"invalid expert id: {eid}")
        out[eid]=Path(path).expanduser().resolve()
    if len(out)<2: raise AnnotationValidationError('at least two experts required')
    return out

def merge(args):
    master_path=Path(args.master).resolve(); key_path=Path(args.key).resolve()
    master=pd.read_csv(master_path,dtype=str,keep_default_na=False); key=pd.read_parquet(key_path)
    visible=['reaction_id','reaction_smiles','reactants','product','expert_label']
    if master.columns.tolist()!=visible: raise AnnotationValidationError('master visible schema mismatch')
    if key.reaction_id.duplicated().any() or set(key.reaction_id.astype(str))!=set(master.reaction_id.astype(str)): raise AnnotationValidationError('master/key ID mismatch')
    experts=expert_args(args.expert); raw_dir=master_path.parent/'raw_expert'; raw_dir.mkdir(parents=True,exist_ok=True)
    rows=[]; raw_info={}
    for eid,source in sorted(experts.items()):
        dest=raw_dir/f'{eid}_{source.name}'
        if dest.exists(): raise AnnotationValidationError(f'refusing to overwrite raw file: {dest}')
        shutil.copy2(source,dest); checked,digest=validate_expert_file(dest,master,eid); raw_info[eid]={'path':str(dest),'sha256':digest}
        for i,row in checked.reset_index(drop=True).iterrows(): rows.append({'reaction_id':str(row.reaction_id),'expert_id':eid,'expert_label':int(row.expert_label),'is_abstain':int(row.expert_label)==3,'source_file_sha256':digest,'annotation_file_row_number':i+1})
    long=pd.DataFrame(rows); atomic_write_parquet(long,Path(args.output).resolve())
    adj=build_adjudication_required(long,master,sorted(experts)); atomic_write_csv(adj,Path(args.adjudication_output).resolve())
    report={'stage':7,'status':'HUMAN_REVIEW_REQUIRED','created_at_utc':datetime.now(timezone.utc).isoformat(),'expert_ids':sorted(experts),'raw_expert_files':raw_info,'long_annotations':{'path':str(Path(args.output).resolve()),'sha256':sha256(Path(args.output).resolve()),'rows':len(long)},'adjudication_required':{'path':str(Path(args.adjudication_output).resolve()),'sha256':sha256(Path(args.adjudication_output).resolve()),'rows':len(adj)},'agreement':agreement_report(long),'human_gate':'STOP_AFTER_PRE_ADJUDICATION_AGREEMENT','expert_labels_generated_by_codex':False}
    atomic_write_json(report,ROOT/'reports/stage7_interrater_agreement.json')
    print(json.dumps(report,indent=2,ensure_ascii=False)); return 0

def finalize(args):
    ann=pd.read_parquet(Path(args.annotations).resolve()); key=pd.read_parquet(Path(args.key).resolve()); adj=pd.read_csv(Path(args.adjudication).resolve(),dtype=str,keep_default_na=False); out=Path(args.output).resolve()
    if out.exists(): raise AnnotationValidationError(f'refusing to overwrite final labels: {out}')
    eids=sorted(ann.expert_id.astype(str).unique()); master=pd.DataFrame({'reaction_id':key.reaction_id.astype(str),'reaction_smiles':key.reaction_smiles,'reactants':key.precursor_smiles,'product':key.product_smiles})
    required=build_adjudication_required(ann,master,eids)
    if set(required.reaction_id)!=set(adj.reaction_id.astype(str)): raise AnnotationValidationError('adjudication ID set mismatch')
    if 'adjudicated_label' not in adj.columns or any(str(x) not in {'0','1','2','3'} for x in adj.adjudicated_label): raise AnnotationValidationError('invalid adjudicated_label; literal 0/1/2/3 required')
    pivot=ann.pivot(index='reaction_id',columns='expert_id',values='expert_label').reindex(columns=eids); ki=key.set_index('reaction_id'); ai=adj.set_index('reaction_id'); rows=[]
    for rid in key.reaction_id.astype(str):
        vals=[pivot.loc[rid,e] for e in eids]; non=[int(v) for v in vals if pd.notna(v) and int(v)!=3]; needs=any(pd.isna(v) or int(v)==3 for v in vals) or len(set(non))>1
        if needs:
            final = int(ai.loc[rid, 'adjudicated_label'])
        else:
            # A unanimous result contains one non-abstain value per expert;
            # accept it when all non-abstain ratings are identical.
            if not non or len(set(non)) != 1:
                raise AnnotationValidationError(f"unresolved label: {rid}")
            final = non[0]
        rows.append({'reaction_id':rid,'reaction_hash':str(ki.loc[rid,'reaction_hash']),'target_id':str(ki.loc[rid,'target_id']),'route_id':str(ki.loc[rid,'route_id']),'step_id':str(ki.loc[rid,'step_id']),'expert_label':None if final==3 else final,'final_status':'ABSTAIN' if final==3 else 'LABELED','final_source':'adjudication' if needs else 'unanimous','n_experts':len(eids),'n_non_abstain':len(non),'original_labels':json.dumps({e:(None if pd.isna(pivot.loc[rid,e]) else int(pivot.loc[rid,e])) for e in eids},sort_keys=True)})
    final_df=pd.DataFrame(rows); atomic_write_parquet(final_df,out); report={'stage':7,'status':'COMPLETE','created_at_utc':datetime.now(timezone.utc).isoformat(),'output':{'path':str(out),'sha256':sha256(out),'rows':len(final_df)},'labeled_n':int((final_df.final_status=='LABELED').sum()),'abstain_n':int((final_df.final_status=='ABSTAIN').sum()),'unanimous_n':int((final_df.final_source=='unanimous').sum()),'adjudication_n':int((final_df.final_source=='adjudication').sum()),'adjudication_input_sha256':sha256(Path(args.adjudication).resolve()),'agreement_before_adjudication':agreement_report(ann),'stage8_started':False}; atomic_write_json(report,ROOT/'reports/stage7_finalization_report.json'); return 0

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='mode',required=True); m=sub.add_parser('merge'); m.add_argument('--master',required=True); m.add_argument('--key',required=True); m.add_argument('--expert',action='append',required=True); m.add_argument('--output',required=True); m.add_argument('--adjudication-output',required=True); f=sub.add_parser('finalize'); f.add_argument('--annotations',required=True); f.add_argument('--key',required=True); f.add_argument('--adjudication',required=True); f.add_argument('--output',required=True); a=ap.parse_args()
    try: return merge(a) if a.mode=='merge' else finalize(a)
    except Exception as exc: print(f'BLOCKED: {type(exc).__name__}: {exc}'); return 1
if __name__=='__main__': raise SystemExit(main())
