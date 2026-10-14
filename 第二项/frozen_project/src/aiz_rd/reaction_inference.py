"""Stage 9 frozen-model inference and feature-provider validation."""
from __future__ import annotations
import hashlib, json, pickle
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import statsmodels
from .difficulty_model import ReactionDifficultyModel
from .chemistry import canonicalize_molecule_smiles, canonicalize_reaction, reaction_hash
from .feasibility import compute_feasibility
from .precedent import ReactionPrecedentIndex, RXNFPRuntime
from .sc_feature import compute_delta_sc, ecdf_right_continuous

FEATURE_ORDER=["d_feas","d_prec","d_sc"]
REACTION_OUTPUT_COLUMNS=["target_id","route_id","step_id","reaction_hash","reaction_smiles","product_smiles","precursor_smiles","p_feas","d_feas","s_max","n_analog","p_prec","d_prec","sc_product","sc_precursor_max","delta_sc","d_sc","p_easy","p_medium","p_difficult","reaction_difficulty","uncertainty","confidence"]
class Stage9Blocked(RuntimeError): pass
def sha256(path: Path)->str:
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest().upper()
class FrozenFeatureProvider:
 def __init__(self,features):
  if 'reaction_hash' not in features: raise Stage9Blocked('frozen feature table lacks reaction_hash')
  self._features=features.drop_duplicates('reaction_hash',keep='first').set_index('reaction_hash')
 def get(self,key):
  try: row=self._features.loc[str(key)]
  except KeyError as e: raise Stage9Blocked(f'unknown frozen reaction_hash: {key}') from e
  return {n:float(row[n]) for n in FEATURE_ORDER}
class OnDemandFeatureProvider:
 def __init__(self,quick_filter,precedent_index,sc_model,ecdf_values,*,mode='deployment',tau=.8,n0=10.):
  self.quick_filter=quick_filter; self.precedent_index=precedent_index; self.sc_model=sc_model; self.ecdf_values=np.asarray(ecdf_values,float); self.mode=str(mode); self.tau=float(tau); self.n0=float(n0)
  if self.mode not in {'deployment','benchmark'} or self.ecdf_values.ndim!=1 or len(self.ecdf_values)==0 or not np.isfinite(self.ecdf_values).all() or np.any(self.ecdf_values[1:]<self.ecdf_values[:-1]): raise Stage9Blocked('invalid frozen on-demand assets')
 def score_components(self,product_smiles,precursor_nodes,*,expected_hash=None):
  if not precursor_nodes: raise Stage9Blocked('zero-reaction route is not applicable')
  precursor,product,canonical=canonicalize_reaction(precursor_nodes,product_smiles); rh=reaction_hash(canonical)
  if expected_hash is not None and str(expected_hash)!=rh: raise Stage9Blocked(f'reaction hash mismatch: {expected_hash} != {rh}')
  feas=compute_feasibility(product,precursor,self.quick_filter); sc=compute_delta_sc(product,precursor_nodes,self.sc_model); vec=self.precedent_index.runtime.embed([canonical])[0]; pr=self.precedent_index.full_corpus_score(vec,rh,mode=self.mode,tau=self.tau,n0=self.n0); dsc=ecdf_right_continuous(self.ecdf_values,float(sc.delta_sc))
  return {'reaction_hash':rh,'reaction_smiles':canonical,'p_feas':float(feas.p_feas),'d_feas':float(feas.d_feas),'s_max':float(pr.s_max),'n_analog':int(pr.n_analog),'p_prec':float(pr.p_prec),'d_prec':float(pr.d_prec),'sc_product':float(sc.sc_product),'sc_precursor_max':float(sc.sc_precursor_max),'delta_sc':float(sc.delta_sc),'d_sc':float(dsc)}
 def get(self,key): raise Stage9Blocked('OnDemandFeatureProvider.get requires molecule components; use score_components')

def build_on_demand_provider(root: Path) -> OnDemandFeatureProvider:
    """Load the frozen Stage 3--5 assets for post-search scoring."""
    env=json.loads((root/'reports/environment_check.json').read_text(encoding='utf-8'))
    stage5=json.loads((root/'reports/stage5_manifest.json').read_text(encoding='utf-8'))
    if env.get('overall_status')!='PASS' or env.get('quick_filter',{}).get('status')!='PASS' or env.get('scscore',{}).get('status')!='PASS': raise Stage9Blocked('BLOCKED_FEATURE_PROVIDER_DRIFT: Stage 3 environment not PASS')
    from aizynthfinder.aizynthfinder import AiZynthExpander
    from aizynthfinder.utils.sc_score import SCScore
    expander=AiZynthExpander(configfile=str(root/'config/config_production.yml')); fk=env['quick_filter'].get('key'); fk=fk[0] if isinstance(fk,list) else fk
    if expander.filter_policy.items != [fk]: raise Stage9Blocked('BLOCKED_FEATURE_PROVIDER_DRIFT: QuickFilter policy mismatch')
    filter_model=Path(env['quick_filter']['model_path']); sc_path=Path(env['scscore']['model_path'])
    if sha256(filter_model)!=str(env['quick_filter']['sha256']).upper() or sha256(sc_path)!=str(env['scscore']['sha256']).upper(): raise Stage9Blocked('BLOCKED_FEATURE_PROVIDER_DRIFT: model hash mismatch')
    index=ReactionPrecedentIndex(root/'artifacts/reference_rxnfp.npy',root/'artifacts/reference_metadata.parquet',root/'artifacts/reference_nn_index.joblib',RXNFPRuntime(),top_k=100)
    ecdf=np.load(root/'artifacts/sc_delta_ecdf.npz',allow_pickle=False)['delta_sc_sorted']
    return OnDemandFeatureProvider(expander.filter_policy[fk],index,SCScore(str(sc_path)),ecdf,mode=str(stage5['precedent_mode']),tau=float(stage5['tau']),n0=float(stage5['n0']))
def load_frozen_model(model_path,metadata_path,stage8_manifest_path):
 m=json.loads(Path(metadata_path).read_text(encoding='utf-8')); s=json.loads(Path(stage8_manifest_path).read_text(encoding='utf-8'))
 if s.get('status')!='PASS' or sha256(model_path)!=str(s.get('model_artifact_sha256','')).upper() or sha256(metadata_path)!=str(s.get('model_metadata_sha256','')).upper(): raise Stage9Blocked('Stage 8 model/metadata prerequisite mismatch')
 if m.get('model_name')!='Ordinal Logistic Regression / OrderedModel' or m.get('distribution')!='logit' or m.get('feature_order')!=FEATURE_ORDER or m.get('label_order')!={'0':'Easy','1':'Medium','2':'Difficult'} or m.get('converged') is not True: raise Stage9Blocked('frozen model identity mismatch')
 if m.get('statsmodels_version') and str(m['statsmodels_version'])!=str(statsmodels.__version__): raise Stage9Blocked('statsmodels compatibility mismatch')
 q33,q67=m.get('q33'),m.get('q67')
 if not isinstance(q33,(int,float)) or not isinstance(q67,(int,float)) or not 0<=q33<=q67<=1: raise Stage9Blocked('invalid frozen thresholds')
 with Path(model_path).open('rb') as f: model=pickle.load(f)
 if not isinstance(model,ReactionDifficultyModel) or model.result is None or not model.converged: raise Stage9Blocked('loaded artifact is not fitted frozen model')
 return model,m,s
def _conf(u,q33,q67): return 'high' if u<=q33 else ('medium' if u<=q67 else 'low')
def score_reactions(features_path,model_path,metadata_path,stage8_manifest_path,output_path):
 model,meta,manifest=load_frozen_model(model_path,metadata_path,stage8_manifest_path)
 if sha256(features_path)!=str(manifest.get('input_file_hashes',{}).get('reaction_features','')).upper() or sha256(features_path)!=str(meta.get('input_feature_table_sha256','')).upper(): raise Stage9Blocked('Stage 6 feature table hash mismatch')
 f=pd.read_parquet(features_path); required=REACTION_OUTPUT_COLUMNS[:17]
 if any(c not in f for c in required): raise Stage9Blocked('missing Stage 6 columns')
 vals=f[['p_feas','d_feas','s_max','n_analog','p_prec','d_prec','sc_product','sc_precursor_max','delta_sc','d_sc']].to_numpy(float)
 if not np.isfinite(vals).all(): raise Stage9Blocked('non-finite Stage 6 feature')
 unique=f.groupby('reaction_hash',sort=False)[FEATURE_ORDER].nunique()
 if (unique>1).any(axis=None): raise Stage9Blocked('inconsistent features per reaction_hash')
 u=f.drop_duplicates('reaction_hash',keep='first'); p=model.predict_proba(u[FEATURE_ORDER])
 if p.shape!=(len(u),3) or not np.isfinite(p).all() or not np.allclose(p.sum(1),1,atol=1e-10): raise Stage9Blocked('invalid model probabilities')
 q=pd.DataFrame({'reaction_hash':u.reaction_hash.to_numpy(),'p_easy':p[:,0],'p_medium':p[:,1],'p_difficult':p[:,2]}); q['reaction_difficulty']=50*q.p_medium+100*q.p_difficult; q['uncertainty']=(4*u.p_feas.to_numpy()*(1-u.p_feas.to_numpy())+(1-u.p_prec.to_numpy()))/2; q['confidence']=[_conf(x,float(meta['q33']),float(meta['q67'])) for x in q.uncertainty]
 if ((q[['p_easy','p_medium','p_difficult']]<0)|(q[['p_easy','p_medium','p_difficult']]>1)).any().any() or ((q.reaction_difficulty<0)|(q.reaction_difficulty>100)|(q.uncertainty<0)|(q.uncertainty>1)).any(): raise Stage9Blocked('inference value outside bounds')
 out=f.merge(q,on='reaction_hash',how='left',sort=False,validate='many_to_one')
 if len(out)!=len(f) or out.reaction_difficulty.isna().any() or not out[['target_id','route_id','step_id','reaction_hash']].reset_index(drop=True).equals(f[['target_id','route_id','step_id','reaction_hash']].reset_index(drop=True)): raise Stage9Blocked('reaction coverage/order mismatch')
 out=out[REACTION_OUTPUT_COLUMNS]; output_path=Path(output_path); output_path.parent.mkdir(parents=True,exist_ok=True); tmp=output_path.with_suffix('.tmp'); out.to_parquet(tmp,index=False); tmp.replace(output_path)
 return {'rows':len(out),'unique_reaction_hash':len(u),'q33':float(meta['q33']),'q67':float(meta['q67']),'model_sha256':sha256(model_path),'metadata_sha256':sha256(metadata_path),'stage8_manifest_sha256':sha256(stage8_manifest_path)}
def validate_provider_equivalence(features_path,limit=20,**kwargs):
 """Recompute the first *limit* unique reactions with frozen Stage 3--5 assets."""
 routes_path=kwargs.get('routes_path')
 if not routes_path: raise Stage9Blocked('BLOCKED_FEATURE_PROVIDER_DRIFT: routes_path required')
 root=Path(features_path).resolve().parents[2]
 env_path=Path(kwargs.get('environment_path') or root/'reports/environment_check.json')
 stage5_path=Path(kwargs.get('stage5_manifest_path') or root/'reports/stage5_manifest.json')
 config_path=Path(kwargs.get('production_config_path') or root/'config/config_production.yml')
 env=json.loads(env_path.read_text(encoding='utf-8')); stage5=json.loads(stage5_path.read_text(encoding='utf-8'))
 if env.get('overall_status')!='PASS' or env.get('quick_filter',{}).get('status')!='PASS' or env.get('scscore',{}).get('status')!='PASS': raise Stage9Blocked('BLOCKED_FEATURE_PROVIDER_DRIFT: Stage 3 environment not PASS')
 from aizynthfinder.aizynthfinder import AiZynthExpander
 from aizynthfinder.utils.sc_score import SCScore
 from .route_extractor import _serialized_reactions
 expander=AiZynthExpander(configfile=str(config_path)); fk=env['quick_filter'].get('key'); fk=fk[0] if isinstance(fk,list) else fk
 if expander.filter_policy.items != [fk]: raise Stage9Blocked('BLOCKED_FEATURE_PROVIDER_DRIFT: QuickFilter policy mismatch')
 filter_model=Path(env['quick_filter']['model_path']); sc_path=Path(env['scscore']['model_path'])
 if sha256(filter_model)!=str(env['quick_filter']['sha256']).upper() or sha256(sc_path)!=str(env['scscore']['sha256']).upper(): raise Stage9Blocked('BLOCKED_FEATURE_PROVIDER_DRIFT: model hash mismatch')
 index=ReactionPrecedentIndex(root/'artifacts/reference_rxnfp.npy',root/'artifacts/reference_metadata.parquet',root/'artifacts/reference_nn_index.joblib',RXNFPRuntime(),top_k=100)
 ecdf=np.load(root/'artifacts/sc_delta_ecdf.npz',allow_pickle=False)['delta_sc_sorted']
 provider=OnDemandFeatureProvider(expander.filter_policy[fk],index,SCScore(str(sc_path)),ecdf,mode=str(stage5['precedent_mode']),tau=float(stage5['tau']),n0=float(stage5['n0']))
 target_map={canonicalize_molecule_smiles(str(row.target_smiles)):str(row.target_id) for row in pd.read_csv(root/'data/raw/targets.csv').itertuples()}
 components={}; data=json.loads(Path(routes_path).read_text(encoding='utf-8'))['data']
 for item in data:
  tid=target_map[canonicalize_molecule_smiles(str(item['target']))]
  for rank,tree in enumerate(item.get('trees',[]),1):
   candidates=[]
   for node in _serialized_reactions(tree):
    precursor,product,canonical=canonicalize_reaction(list(node.precursors_raw),node.product_raw); candidates.append((node,precursor,product,canonical))
   candidates.sort(key=lambda x:(x[0].reaction_depth,x[2],x[1],x[0].original_serialized_index))
   rid=f'{tid}__route_{rank:03d}'
   for step,(node,precursor,product,canonical) in enumerate(candidates,1):
    components.setdefault(reaction_hash(canonical),(product,[canonicalize_molecule_smiles(x) for x in node.precursors_raw]))
 frame=pd.read_parquet(features_path); frozen=FrozenFeatureProvider(frame); keys=frame.reaction_hash.drop_duplicates().astype(str).head(limit).tolist(); mismatches=[]; max_abs=0.
 for key in keys:
  if key not in components: raise Stage9Blocked(f'BLOCKED_FEATURE_PROVIDER_DRIFT: missing route component {key}')
  product,nodes=components[key]; actual=provider.score_components(product,nodes,expected_hash=key); expected=frozen.get(key); diffs={n:abs(float(expected[n])-float(actual[n])) for n in FEATURE_ORDER}; max_abs=max(max_abs,*diffs.values())
  if max(diffs.values())>1e-6: mismatches.append({'reaction_hash':key,'absolute_differences':diffs,'frozen':expected,'on_demand':{n:actual[n] for n in FEATURE_ORDER}})
 if mismatches: raise Stage9Blocked(f'BLOCKED_FEATURE_PROVIDER_DRIFT: {mismatches[0]}')
 return {'tested':len(keys),'mismatches':0,'max_abs_difference':max_abs,'status':'PASS'}
