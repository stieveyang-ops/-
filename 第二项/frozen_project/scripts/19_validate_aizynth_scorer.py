from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from aizynthfinder.context.config import Configuration
from aizynthfinder.context.scoring import ScorerCollection
from aizynthfinder.reactiontree import ReactionTree
from aiz_rd.aizynth_scorer import ReactionDifficultyScorer, reaction_hash_from_tree_node
from aiz_rd.route_ranker import RouteDifficultyEvaluator
from aiz_rd.reaction_inference import build_on_demand_provider, load_frozen_model

def main():
 p=argparse.ArgumentParser(); p.add_argument('--config',default=str(ROOT/'config/config_benchmark.yml')); p.add_argument('--routes',default=str(ROOT/'data/generated/routes_raw.json')); p.add_argument('--scored',default=str(ROOT/'outputs/scored_reactions.parquet')); p.add_argument('--report',default=str(ROOT/'reports/stage9_scorer_integration_report.json')); a=p.parse_args()
 report={'stage':9,'status':'BLOCKED','scorer_name':'reaction ease score','post_search_only':True}
 try:
  cfg=Configuration.from_file(a.config); root=Path(a.config).resolve().parents[1]; model,meta,_=load_frozen_model(root/'artifacts/difficulty_model.pkl',root/'artifacts/difficulty_model_metadata.json',root/'reports/stage8_manifest.json'); provider=build_on_demand_provider(root); evaluator=RouteDifficultyEvaluator(float(meta['q33']),float(meta['q67']),feature_provider=provider,model=model); scorer=ReactionDifficultyScorer(cfg,evaluator=evaluator); coll=ScorerCollection(cfg); coll.load(scorer)
  raw=json.loads(Path(a.routes).read_text(encoding='utf-8')); tree=ReactionTree.from_dict(raw['data'][0]['trees'][0]); value=float(scorer(tree));
  if not 0<=value<=1: raise RuntimeError(f'scorer output outside [0,1]: {value}')
  report.update({'status':'PASS','collection_load':'PASS','smoke_test':'PASS','score':value,'scorer_class':'ReactionDifficultyScorer','feature_provider':'OnDemandFeatureProvider','aizynthfinder_version':'4.4.1','mcts_modified':False})
 except Exception as e: report['error']=f'{type(e).__name__}: {e}'
 Path(a.report).write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2)); return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
