from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from aiz_rd.reaction_inference import score_reactions

def main():
 p=argparse.ArgumentParser(); p.add_argument('--features',default=str(ROOT/'data/processed/reaction_features.parquet')); p.add_argument('--model',default=str(ROOT/'artifacts/difficulty_model.pkl')); p.add_argument('--metadata',default=str(ROOT/'artifacts/difficulty_model_metadata.json')); p.add_argument('--stage8-manifest',default=str(ROOT/'reports/stage8_manifest.json')); p.add_argument('--output',default=str(ROOT/'outputs/scored_reactions.parquet')); p.add_argument('--preview',default=str(ROOT/'reports/stage9_reaction_inference_preview.csv')); p.add_argument('--report',default=str(ROOT/'reports/stage9_reaction_inference_report.json')); a=p.parse_args()
 report={'stage':9,'status':'BLOCKED'}
 try:
  info=score_reactions(Path(a.features),Path(a.model),Path(a.metadata),Path(a.stage8_manifest),Path(a.output)); import pandas as pd; scored=pd.read_parquet(a.output); scored.head(10).to_csv(a.preview,index=False); report.update({'status':'PASS','input_path':str(Path(a.features).resolve()),'output_path':str(Path(a.output).resolve()),'preview_path':str(Path(a.preview).resolve()),'feature_order':['d_feas','d_prec','d_sc'],'formula':'D_reaction=50*p_medium+100*p_difficult; U=[4*p_feas*(1-p_feas)+(1-p_prec)]/2',**info})
 except Exception as e: report['error']=f'{type(e).__name__}: {e}'
 Path(a.report).write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
