from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from aiz_rd.route_ranker import rank_routes

def main():
 p=argparse.ArgumentParser(); p.add_argument('--routes',default=str(ROOT/'data/generated/routes_raw.json')); p.add_argument('--steps',default=str(ROOT/'data/processed/reaction_steps_raw.parquet')); p.add_argument('--scored-reactions',default=str(ROOT/'outputs/scored_reactions.parquet')); p.add_argument('--targets',default=str(ROOT/'data/raw/targets.csv')); p.add_argument('--output-parquet',default=str(ROOT/'outputs/scored_routes.parquet')); p.add_argument('--output-csv',default=str(ROOT/'outputs/scored_routes.csv')); p.add_argument('--output-json',default=str(ROOT/'outputs/scored_routes.json')); p.add_argument('--preview',default=str(ROOT/'reports/stage9_route_ranking_preview.csv')); p.add_argument('--q33',type=float,default=0.3005421128682305); p.add_argument('--q67',type=float,default=0.5006582129614043); p.add_argument('--report',default=str(ROOT/'reports/stage9_route_ranking_report.json')); a=p.parse_args()
 report={'stage':9,'status':'BLOCKED'}
 try:
  info=rank_routes(Path(a.routes),Path(a.steps),Path(a.scored_reactions),Path(a.targets),Path(a.output_parquet),Path(a.output_csv),Path(a.output_json),Path(a.preview),a.q33,a.q67); report.update({'status':'PASS','aggregation':{'bottleneck':'max','mean':'arithmetic mean','route_uncertainty':'max'},'ranking_rule':'solved desc, bottleneck asc, mean asc, original_state_score desc, original_rank asc, route_id asc','q33':a.q33,'q67':a.q67,**info})
 except Exception as e: report['error']=f'{type(e).__name__}: {e}'
 Path(a.report).write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
