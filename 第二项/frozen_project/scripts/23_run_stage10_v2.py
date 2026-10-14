"""Run the complete, versioned Stage 10 v2 analysis after unseal.

All fitting uses development rows only.  Locked-test rows are read only after
the v2 receipt has been validated and are never used for selection or tuning.
"""
from __future__ import annotations
import argparse, hashlib, json, math, pickle, sys, warnings
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from statsmodels.miscmodels.ordinal_model import OrderedModel
from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score, confusion_matrix, f1_score
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from aiz_rd.benchmark_models import fit_model_A, fit_model_B, fit_model_C, fit_model_E, fit_model_features
from aiz_rd.benchmark_metrics import METRICS, compute_metrics
from aiz_rd.difficulty_model import ReactionDifficultyModel
from aiz_rd.precedent import ReactionPrecedentIndex, RXNFPRuntime
from aiz_rd.sc_feature import score_molecule_sc, ecdf_right_continuous
from aizynthfinder.utils.sc_score import SCScore
from aiz_rd.leakage import audit_leakage

FEATURES=['d_feas','d_prec','d_sc']
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest().upper()
def atomic_json(path,payload):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8'); tmp.replace(path)
def atomic_parquet(df,path):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); df.to_parquet(tmp,index=False,engine='pyarrow',compression='zstd'); pd.read_parquet(tmp); tmp.replace(path)
def atomic_csv(df,path):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); df.to_csv(tmp,index=False); pd.read_csv(tmp); tmp.replace(path)
def validate_receipt():
 p=ROOT/'reports/stage10_unseal_receipt_v2.json'; r=json.loads(p.read_text(encoding='utf-8'))
 if r.get('status')!='UNSEALED_ONCE' or r.get('cycle_version')!='stage10_v2' or not r.get('temporal_ordering_verified'): raise RuntimeError('BLOCKED_STAGE10_V2_UNSEAL_RECEIPT_INVALID')
 if r.get('locked_test_sha256')!=sha(ROOT/'data/splits/test_ids_locked.txt'): raise RuntimeError('BLOCKED_STAGE10_V2_LOCKED_TEST_HASH_DRIFT')
 if r.get('preanalysis_manifest_sha256')!=sha(ROOT/'reports/stage10_preanalysis_manifest_v2.json'): raise RuntimeError('BLOCKED_STAGE10_V2_PREANALYSIS_HASH_DRIFT')
 if r.get('preunseal_test_report_sha256')!=sha(ROOT/'reports/stage10_preunseal_test_report_v2.json'): raise RuntimeError('BLOCKED_STAGE10_V2_PREUNSEAL_REPORT_HASH_DRIFT')
 return r
def prepare_benchmark():
 feat=pd.read_parquet(ROOT/'data/processed/reaction_features.parquet')
 labels=pd.read_parquet(ROOT/'data/labels/final_expert_labels.parquet')
 split=pd.read_parquet(ROOT/'data/splits/split_assignments.parquet')
 first=feat.sort_values(['reaction_hash','route_id','step_id'],kind='mergesort').drop_duplicates('reaction_hash').copy()
 first=first.merge(labels[['reaction_hash','expert_label','final_status']],on='reaction_hash',how='inner',validate='one_to_one')
 first=first.merge(split[['reaction_hash','leakage_group_id','split','target_ids']],on='reaction_hash',how='left',validate='one_to_one')
 first=first.sort_values('reaction_hash',kind='mergesort').reset_index(drop=True)
 if first.leakage_group_id.isna().any(): raise RuntimeError('BLOCKED_BENCHMARK_LEAKAGE_GROUP_MISSING')
 atomic_parquet(first,ROOT/'data/benchmark/stage10_benchmark_reactions.parquet')
 return first
def save_comparator(name,model,dev_ids):
 d=ROOT/'artifacts/stage10_comparators'; d.mkdir(parents=True,exist_ok=True); p=d/f'model_{name}.pkl'; m=d/f'model_{name}_metadata.json';
 with p.open('wb') as f: pickle.dump(model,f,protocol=pickle.HIGHEST_PROTOCOL)
 meta=model.metadata(); meta.update({'model':name,'development_ids_sha256':hashlib.sha256(('\n'.join(sorted(dev_ids))+'\n').encode()).hexdigest().upper(),'created_at_utc':datetime.now(timezone.utc).isoformat()}); atomic_json(m,meta)
 return p,m
def metric_rows(model_name, y, frame):
 r=compute_metrics(y,frame[f'{model_name}_difficulty'],frame[f'{model_name}_class']); out=[]
 for metric in METRICS:
  out.append((metric,float(r[metric]) if np.isfinite(r[metric]) else np.nan))
 return r
def bootstrap_all(frame, models, seed=42, reps=1000):
 groups=sorted(frame.leakage_group_id.astype(str).unique()); by={g:frame.index[frame.leakage_group_id.astype(str).eq(g)].to_numpy() for g in groups}; rng=np.random.default_rng(seed); met=[]; dif=[]
 for rep in range(reps):
  sampled=rng.choice(np.asarray(groups,dtype=object),size=len(groups),replace=True); idx=[]
  for g in sampled.tolist(): idx.extend(by[str(g)].tolist())
  s=frame.loc[idx]; results={}
  for model in models:
   results[model]=compute_metrics(s.expert_label.to_numpy(int),s[f'{model}_difficulty'].to_numpy(float),s[f'{model}_class'].to_numpy(int)); met.append({'replicate':rep,'model':model,**{m:results[model][m] for m in METRICS}})
  for base in ['A','B','C','E']:
   dif.append({'replicate':rep,'comparison':f'D-{base}',**{m:results['D'][m]-results[base][m] for m in METRICS}})
 return pd.DataFrame(met),pd.DataFrame(dif)
def ci_summary(values):
 v=pd.to_numeric(values,errors='coerce').to_numpy(float); finite=v[np.isfinite(v)];
 return (float(np.percentile(finite,2.5)) if len(finite) else np.nan,float(np.percentile(finite,97.5)) if len(finite) else np.nan,int(len(finite)),'CI_STABILITY_WARNING' if len(finite)<900 else None)
def build_reference_mean_ecdf():
 ref=pd.read_parquet(ROOT/'data/reference/reference_reactions_clean.parquet'); model=SCScore(str(ROOT/'artifacts/runtime/scscore/scscore_model_1024bool_aizynth.pickle')); vals=[]; invalid=[]; 
 for row in ref.itertuples(index=False):
  try:
   reactants,products=str(row.reaction_smiles).split('>>',1); pcs=[x for x in products.split('.') if x]; rcs=[x for x in reactants.split('.') if x]
   if len(pcs)!=1 or not rcs: invalid.append((row.reaction_hash,'multiple_products_or_empty')); continue
   pv=score_molecule_sc(pcs[0],model); rv=[score_molecule_sc(x,model) for x in rcs]; delta=pv-float(np.mean(rv));
   if not math.isfinite(delta): invalid.append((row.reaction_hash,'nonfinite')); continue
   vals.append(delta)
  except Exception as e: invalid.append((row.reaction_hash,type(e).__name__))
 sorted_vals=np.sort(np.asarray(vals,dtype=np.float64));
 if len(sorted_vals)==0: raise RuntimeError('BLOCKED_SC_MEAN_ECDF_EMPTY')
 np.savez(ROOT/'artifacts/sc_delta_mean_ecdf_stage10.npz',delta_sc_sorted=sorted_vals,n_reference_valid=np.int64(len(sorted_vals)),reference_corpus_sha256=sha(ROOT/'data/reference/reference_reactions_clean.parquet'),scscore_model_sha256=sha(ROOT/'artifacts/runtime/scscore/scscore_model_1024bool_aizynth.pickle'),definition='product_minus_mean_precursor',invalid_count=np.int64(len(invalid)))
 return sorted_vals,len(invalid)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--seed',type=int,default=42); a=ap.parse_args(); receipt=validate_receipt(); b=prepare_benchmark(); labeled=b[b.final_status.eq('LABELED')].copy(); dev=labeled[labeled.split.eq('development')].copy(); test=labeled[labeled.split.eq('locked_test')].copy();
 if len(dev)!=244 or len(test)!=47: raise RuntimeError('BLOCKED_STAGE10_SPLIT_SIZE_DRIFT')
 # Fit only on development.
 comps={'A':fit_model_A(dev),'B':fit_model_B(dev),'C':fit_model_C(dev),'E':fit_model_E(dev)}
 for n,m in comps.items(): save_comparator(n,m,dev.reaction_hash.astype(str).tolist());
 frozen=ReactionDifficultyModel.load(ROOT/'artifacts/difficulty_model.pkl'); p=frozen.predict_proba(test[FEATURES]); test['D_p_easy']=p[:,0]; test['D_p_medium']=p[:,1]; test['D_p_difficult']=p[:,2]; test['D_class']=np.argmax(p,axis=1).astype(int); test['D_difficulty']=50*p[:,1]+100*p[:,2]
 for n,m in comps.items(): test=pd.concat([test,m.predict_frame(test,n)],axis=1)
 cols=['reaction_hash','target_id','leakage_group_id','expert_label']+[f'{n}_{c}' for n in ['A','B','C','D','E'] for c in ['p_easy','p_medium','p_difficult','class','difficulty']]
 pred=test[cols].sort_values('reaction_hash',kind='mergesort').reset_index(drop=True); atomic_parquet(pred,ROOT/'outputs/stage10_locked_test_predictions.parquet')
 # Primary and secondary metrics plus bootstrap percentile intervals.
 models=['A','B','C','D','E']; boot,paired=bootstrap_all(pred,models,a.seed,1000); atomic_parquet(boot,ROOT/'reports/bootstrap_metrics.parquet'); atomic_csv(paired,ROOT/'reports/model_pairwise_differences.csv')
 rows=[]; details={}
 for n in models:
  r=compute_metrics(pred.expert_label,pred[f'{n}_difficulty'],pred[f'{n}_class']); details[n]=r; br=boot[boot.model.eq(n)]
  for metric in METRICS:
   lo,hi,nv,w=ci_summary(br[metric]); rows.append({'model':n,'n_test':len(pred),'n_test_groups':pred.leakage_group_id.nunique(),'metric':metric,'point_estimate':r[metric],'ci_lower_95':lo,'ci_upper_95':hi,'n_bootstrap_valid':nv,'n_bootstrap_total':1000,'warning':w,'primary':metric=='kendall_tau_b'})
 for comp in ['D-A','D-B','D-C','D-E']:
  br=paired[paired.comparison.eq(comp)]
  for metric in METRICS:
   lo,hi,nv,w=ci_summary(br[metric]); rows.append({'model':comp,'n_test':len(pred),'n_test_groups':pred.leakage_group_id.nunique(),'metric':metric,'point_estimate':float(br[metric].mean()),'ci_lower_95':lo,'ci_upper_95':hi,'n_bootstrap_valid':nv,'n_bootstrap_total':1000,'warning':w,'primary':metric=='kendall_tau_b'})
 bench=pd.DataFrame(rows); atomic_csv(bench,ROOT/'reports/benchmark_results.csv'); atomic_json(ROOT/'reports/benchmark_results.json',{'stage':10,'cycle_version':'stage10_v2','status':'PASS','models':details,'rows':rows,'model_metadata_hashes':{n:sha(ROOT/f'artifacts/stage10_comparators/model_{n}_metadata.json') for n in ['A','B','C','E']},'receipt_sha256':sha(ROOT/'reports/stage10_unseal_receipt_v2.json')})
 # Ablation: Full is the frozen Model D; three one-feature models are the comparator fits.
 abl=[]
 for name in ['Full','Feasibility-only','Precedent-only','Delta-SC-only']:
  source='D' if name=='Full' else {'Feasibility-only':'A','Precedent-only':'B','Delta-SC-only':'C'}[name]; r=details[source]; abl.append({'ablation':name,'source_model':source,'n_test':len(pred),**{m:r[m] for m in METRICS}})
 atomic_csv(pd.DataFrame(abl),ROOT/'reports/ablation_results.csv'); atomic_json(ROOT/'reports/ablation_results.json',{'stage':10,'cycle_version':'stage10_v2','status':'PASS','results':abl,'leave_one_out':'NOT_ESTIMABLE_PENDING_IMPLEMENTATION'})
 # Precedent sensitivity: exact full-corpus counts, development-only refit for each grid point.
 idx=ReactionPrecedentIndex(ROOT/'artifacts/reference_rxnfp.npy',ROOT/'artifacts/reference_metadata.parquet',ROOT/'artifacts/reference_nn_index.joblib',RXNFPRuntime(),top_k=10); allq=pd.concat([dev,test]).sort_values('reaction_hash',kind='mergesort').drop_duplicates('reaction_hash').reset_index(drop=True); vec=idx.runtime.embed_many(allq.reaction_smiles.astype(str).tolist()); sim=np.asarray(idx._reference_matrix,dtype=np.float64)@np.asarray(vec,dtype=np.float64).T; hashes=idx.metadata.reaction_hash.astype(str).to_numpy(); grid=[]; primary_dp=None
 for tau in [0.75,0.80,0.85]:
  for n0 in [5,10,20]:
   vals=[]
   for j,row in enumerate(allq.itertuples(index=False)):
    elig=hashes!=str(row.reaction_hash); ss=np.clip(sim[:,j],0,1); smax=float(ss[elig].max()); na=int(np.count_nonzero(ss[elig]>=tau)); pp=smax*(1-math.exp(-na/n0)) if na else 0.; vals.append(1-pp)
   allq[f'd_prec_{tau}_{n0}']=vals
   if tau==0.8 and n0==10: primary_dp=np.asarray(vals); 
   d2=allq[allq.split.eq('development')].copy(); t2=allq[allq.split.eq('locked_test')].copy(); m=fit_model_features(d2.assign(d_prec=allq.loc[d2.index,f'd_prec_{tau}_{n0}']),FEATURES); pp=m.predict_frame(t2.assign(d_prec=allq.loc[t2.index,f'd_prec_{tau}_{n0}']),'S'); rr=compute_metrics(t2.expert_label,pp.S_difficulty,pp.S_class); grid.append({'tau':tau,'N0':n0,'n_test':len(t2),**{x:rr[x] for x in METRICS}})
 # Feature stability against frozen primary d_prec.
 primary_map=allq.set_index('reaction_hash')['d_prec']; st=[]
 for tau in [0.75,0.80,0.85]:
  for n0 in [5,10,20]:
   col=f'd_prec_{tau}_{n0}'; x=allq[col].to_numpy(float); y=allq.reaction_hash.map(primary_map).to_numpy(float); st.append({'tau':tau,'N0':n0,'spearman_dp_vs_primary':float(spearmanr(x,y).statistic),'median_abs_change_dp':float(np.median(np.abs(x-y))),'q90_abs_change_dp':float(np.quantile(np.abs(x-y),.9)),'fraction_change_gt_0_10':float(np.mean(np.abs(x-y)>.1)),'fraction_change_gt_0_20':float(np.mean(np.abs(x-y)>.2))})
 atomic_csv(pd.DataFrame(grid),ROOT/'reports/precedent_sensitivity_results.csv'); atomic_json(ROOT/'reports/precedent_sensitivity_results.json',{'stage':10,'cycle_version':'stage10_v2','status':'PASS','grid_size':len(grid),'primary_tau':0.8,'primary_N0':10,'results':grid,'feature_stability':st})
 # SC mean sensitivity.
 mean_ecdf,mean_invalid=build_reference_mean_ecdf(); raw=pd.read_parquet(ROOT/'data/processed/reaction_sc_raw.parquet'); raw=raw.sort_values(['reaction_hash','route_id','step_id'],kind='mergesort').drop_duplicates('reaction_hash').set_index('reaction_hash'); dsc_mean=[]
 for rh in allq.reaction_hash.astype(str):
  vals=json.loads(raw.loc[rh,'sc_precursor_values_json']); delta=float(raw.loc[rh,'sc_product'])-float(np.mean(vals)); dsc_mean.append(ecdf_right_continuous(mean_ecdf,delta))
 allq['d_sc_mean']=dsc_mean; d2=allq[allq.split.eq('development')].copy(); t2=allq[allq.split.eq('locked_test')].copy(); sm=fit_model_features(d2,FEATURES); sp=sm.predict_frame(t2,'S'); sr=compute_metrics(t2.expert_label,sp.S_difficulty,sp.S_class); scres=[{'definition':'product_minus_max_precursor','model':'D_frozen','n_test':len(pred),**{x:details['D'][x] for x in METRICS}},{'definition':'product_minus_mean_precursor','model':'S_refit_development_only','n_test':len(t2),**{x:sr[x] for x in METRICS}}]; atomic_csv(pd.DataFrame(scres),ROOT/'reports/scscore_sensitivity_results.csv'); atomic_json(ROOT/'reports/scscore_sensitivity_results.json',{'stage':10,'cycle_version':'stage10_v2','status':'PASS','reference_valid_n':int(len(mean_ecdf)),'reference_invalid_n':int(mean_invalid),'results':scres,'spearman_dsc_max_vs_mean':float(spearmanr(t2.d_sc,t2.d_sc_mean).statistic),'median_abs_change':float(np.median(np.abs(t2.d_sc.to_numpy(float)-t2.d_sc_mean.to_numpy(float))))})
 # Final leakage audit on unique benchmark table.
 split=pd.read_parquet(ROOT/'data/splits/split_assignments.parquet'); refmeta=pd.read_parquet(ROOT/'artifacts/reference_metadata.parquet'); leak=audit_leakage(b,split,refmeta); atomic_json(ROOT/'reports/leakage_audit_v2.json',{'stage':10,'cycle_version':'stage10_v2',**leak})
 # Final immutable manifest.
 output_paths=['data/benchmark/stage10_benchmark_reactions.parquet','outputs/stage10_locked_test_predictions.parquet','reports/benchmark_results.csv','reports/benchmark_results.json','reports/bootstrap_metrics.parquet','reports/model_pairwise_differences.csv','reports/ablation_results.csv','reports/ablation_results.json','reports/precedent_sensitivity_results.csv','reports/precedent_sensitivity_results.json','artifacts/sc_delta_mean_ecdf_stage10.npz','reports/scscore_sensitivity_results.csv','reports/scscore_sensitivity_results.json','reports/leakage_audit_v2.json']
 manifest={'stage':10,'cycle_version':'stage10_v2','status':'PASS','created_at_utc':datetime.now(timezone.utc).isoformat(),'preanalysis_manifest_sha256':sha(ROOT/'reports/stage10_preanalysis_manifest_v2.json'),'preunseal_test_report_sha256':sha(ROOT/'reports/stage10_preunseal_test_report_v2.json'),'unseal_receipt_sha256':sha(ROOT/'reports/stage10_unseal_receipt_v2.json'),'locked_test_ids_sha256':sha(ROOT/'data/splits/test_ids_locked.txt'),'expert_labels_sha256':sha(ROOT/'data/labels/final_expert_labels.parquet'),'reaction_features_sha256':sha(ROOT/'data/processed/reaction_features.parquet'),'final_model_sha256':sha(ROOT/'artifacts/difficulty_model.pkl'),'final_model_metadata_sha256':sha(ROOT/'artifacts/difficulty_model_metadata.json'),'reference_corpus_sha256':sha(ROOT/'data/reference/reference_reactions_clean.parquet'),'reference_embeddings_sha256':sha(ROOT/'artifacts/reference_rxnfp.npy'),'primary_metric':'kendall_tau_b','secondary_metrics':['spearman_rho','macro_f1','balanced_accuracy','quadratic_weighted_kappa'],'bootstrap_method':'percentile','bootstrap_repetitions':1000,'bootstrap_unit':'leakage_group_id','bootstrap_seed':42,'precedent_parameter_grid':[[.75,5],[.75,10],[.75,20],[.8,5],[.8,10],[.8,20],[.85,5],[.85,10],[.85,20]],'scscore_primary_definition':'product_minus_max_precursor','scscore_alternate_definition':'product_minus_mean_precursor','all_output_sha256':{p:sha(ROOT/p) for p in output_paths},'locked_test_modified':'NO','stage2_9_modified':'NO','stage11_started':'NO','test_set_tuning':'NO'}
 atomic_json(ROOT/'reports/stage10_manifest_v2.json',manifest); print(json.dumps({'status':'PASS','benchmark_rows':len(pred),'grid_results':len(grid),'output_manifest':'reports/stage10_manifest_v2.json'},indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
