"""Corrected Stage 10 v2.2 formal analysis.

This cycle is isolated from v2/v2.1 outputs.  It excludes abstentions from the
primary benchmark, reports bootstrap undefined reasons, fits all estimable
leave-one-out models, and uses d_sc_mean for the alternate SCScore model.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, math, pickle, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import spearmanr
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('stage10base',ROOT/'scripts/23_run_stage10_v2.py'); base=importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
from aiz_rd.difficulty_model import ReactionDifficultyModel
from aiz_rd.sc_feature import score_molecule_sc, ecdf_right_continuous
from aizynthfinder.utils.sc_score import SCScore

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  block=f.read(1024*1024)
  while block:
   h.update(block); block=f.read(1024*1024)
 return h.hexdigest().upper()
def aj(path,payload):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8'); tmp.replace(path)
def apq(df,path):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); df.to_parquet(tmp,index=False,engine='pyarrow',compression='zstd'); pd.read_parquet(tmp); tmp.replace(path)
def acsv(df,path):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); df.to_csv(tmp,index=False); pd.read_csv(tmp); tmp.replace(path)
def validate_receipt():
 p=ROOT/'reports/stage10_unseal_receipt_v22.json'; r=json.loads(p.read_text(encoding='utf-8'))
 if r.get('status')!='UNSEALED_ONCE' or r.get('cycle_version')!='stage10_v2.2' or not r.get('temporal_ordering_verified'): raise RuntimeError('BLOCKED_STAGE10_V22_UNSEAL_RECEIPT_INVALID')
 if r.get('locked_test_sha256')!=sha(ROOT/'data/splits/test_ids_locked.txt') or r.get('preanalysis_manifest_sha256')!=sha(ROOT/'reports/stage10_preanalysis_manifest_v22.json') or r.get('preunseal_test_report_sha256')!=sha(ROOT/'reports/stage10_preunseal_test_report_v22.json'): raise RuntimeError('BLOCKED_STAGE10_V22_PROVENANCE_HASH_DRIFT')
 return r
def make_benchmark():
 f=pd.read_parquet(ROOT/'data/processed/reaction_features.parquet'); l=pd.read_parquet(ROOT/'data/labels/final_expert_labels.parquet'); s=pd.read_parquet(ROOT/'data/splits/split_assignments.parquet')
 b=f.sort_values(['reaction_hash','route_id','step_id'],kind='mergesort').drop_duplicates('reaction_hash').merge(l[['reaction_hash','expert_label','final_status']],on='reaction_hash',validate='one_to_one').merge(s[['reaction_hash','leakage_group_id','split','target_ids']],on='reaction_hash',validate='one_to_one')
 abstain=int((~b.expert_label.isin([0,1,2])).sum()); b=b[b.final_status.eq('LABELED') & b.expert_label.isin([0,1,2])].sort_values('reaction_hash',kind='mergesort').reset_index(drop=True)
 if len(b)!=291 or b.leakage_group_id.isna().any(): raise RuntimeError('BLOCKED_STAGE10_V22_BENCHMARK_FILTER')
 apq(b,ROOT/'data/benchmark/stage10_benchmark_reactions_v22.parquet'); return b,abstain
def save_comp(name,model,ids):
 d=ROOT/'artifacts/stage10_comparators_v22'; d.mkdir(parents=True,exist_ok=True); p=d/f'model_{name}.pkl'; m=d/f'model_{name}_metadata.json'
 with p.open('wb') as fh: pickle.dump(model,fh,protocol=pickle.HIGHEST_PROTOCOL)
 meta=model.metadata(); meta.update({'model':name,'cycle_version':'stage10_v2.2','development_ids_sha256':hashlib.sha256(('\n'.join(sorted(ids))+'\n').encode()).hexdigest().upper()}); aj(m,meta)
def bootstrap_with_reasons(frame,models,reps=1000,seed=42):
 groups=sorted(frame.leakage_group_id.astype(str).unique()); by={g:frame.index[frame.leakage_group_id.astype(str).eq(g)].to_numpy() for g in groups}; rng=np.random.default_rng(seed); met=[]; pair=[]
 for rep in range(reps):
  sampled=rng.choice(np.asarray(groups,dtype=object),size=len(groups),replace=True); idx=[]
  for g in sampled.tolist(): idx.extend(by[str(g)].tolist())
  s=frame.loc[idx]; rr={}
  for model in models:
   rr[model]=base.compute_metrics(s.expert_label,s[f'{model}_difficulty'],s[f'{model}_class'])
   for metric in base.METRICS:
    value=rr[model][metric]; reason=None if np.isfinite(value) else ('constant_or_single_class' if metric in ('kendall_tau_b','spearman_rho','quadratic_weighted_kappa') else 'undefined_class_metric')
    met.append({'replicate':rep,'model':model,metric:float(value) if np.isfinite(value) else np.nan,'metric_name':metric,'undefined_reason':reason})
  for comp in ['D-A','D-B','D-C','D-E']:
   aa,bb=comp.split('-');
   for metric in base.METRICS:
    value=rr[aa][metric]-rr[bb][metric] if np.isfinite(rr[aa][metric]) and np.isfinite(rr[bb][metric]) else np.nan
    pair.append({'replicate':rep,'comparison':comp,'metric':metric,'value':float(value) if np.isfinite(value) else np.nan,'undefined_reason':None if np.isfinite(value) else 'one_or_both_model_metrics_undefined'})
 return pd.DataFrame(met),pd.DataFrame(pair)
def summarize_long(df, key_col, value_col):
 rows=[]
 for key,g in df.groupby(key_col,sort=True):
  for metric,mg in g.groupby('metric_name' if 'metric_name' in g.columns else 'metric',sort=True):
   vals=pd.to_numeric(mg[value_col],errors='coerce').to_numpy(float); finite=vals[np.isfinite(vals)]; rows.append({'key':key,'metric':metric,'ci_lower_95':float(np.percentile(finite,2.5)) if len(finite) else np.nan,'ci_upper_95':float(np.percentile(finite,97.5)) if len(finite) else np.nan,'n_bootstrap_valid':int(len(finite)),'n_bootstrap_total':1000,'warning':'CI_STABILITY_WARNING' if len(finite)<900 else None})
 return rows
def mean_ecdf():
 ref=pd.read_parquet(ROOT/'data/reference/reference_reactions_clean.parquet'); sm=SCScore(str(ROOT/'artifacts/runtime/scscore/scscore_model_1024bool_aizynth.pickle')); vals=[]; invalid=0
 for row in ref.itertuples(index=False):
  try:
   rs,ps=str(row.reaction_smiles).split('>>',1); rc=[x for x in rs.split('.') if x]; pc=[x for x in ps.split('.') if x]
   if len(pc)!=1 or not rc: invalid+=1; continue
   v=score_molecule_sc(pc[0],sm)-float(np.mean([score_molecule_sc(x,sm) for x in rc]));
   if math.isfinite(v): vals.append(v)
   else: invalid+=1
  except Exception: invalid+=1
 arr=np.sort(np.asarray(vals,float));
 if len(arr)!=4748: raise RuntimeError('BLOCKED_STAGE10_V22_SC_MEAN_ECDF_COUNT')
 np.savez(ROOT/'artifacts/sc_delta_mean_ecdf_stage10_v22.npz',delta_sc_sorted=arr,n_reference_valid=np.int64(len(arr)),reference_corpus_sha256=sha(ROOT/'data/reference/reference_reactions_clean.parquet'),scscore_model_sha256=sha(ROOT/'artifacts/runtime/scscore/scscore_model_1024bool_aizynth.pickle'),definition='product_minus_mean_precursor',invalid_count=np.int64(invalid))
 return arr,invalid
def main():
 argparse.ArgumentParser().parse_args(); validate_receipt(); b,abstain=make_benchmark(); dev=b[b.split.eq('development')].copy(); test=b[b.split.eq('locked_test')].copy()
 comps={'A':base.fit_model_A(dev),'B':base.fit_model_B(dev),'C':base.fit_model_C(dev),'E':base.fit_model_E(dev)}
 for n,m in comps.items(): save_comp(n,m,dev.reaction_hash.astype(str).tolist())
 frozen=ReactionDifficultyModel.load(ROOT/'artifacts/difficulty_model.pkl'); p=frozen.predict_proba(test[base.FEATURES]); test['D_p_easy']=p[:,0]; test['D_p_medium']=p[:,1]; test['D_p_difficult']=p[:,2]; test['D_class']=np.argmax(p,axis=1); test['D_difficulty']=50*p[:,1]+100*p[:,2]
 for n,m in comps.items(): test=pd.concat([test,m.predict_frame(test,n)],axis=1)
 cols=['reaction_hash','target_id','leakage_group_id','expert_label']+[f'{n}_{c}' for n in ['A','B','C','D','E'] for c in ['p_easy','p_medium','p_difficult','class','difficulty']]; pred=test[cols].sort_values('reaction_hash',kind='mergesort').reset_index(drop=True); apq(pred,ROOT/'outputs/stage10_locked_test_predictions_v22.parquet')
 models=['A','B','C','D','E']; wide_boot,wide_pair=base.bootstrap_all(pred,models,42,1000)
 # Expand the frozen draws into a long audit table with explicit undefined reasons.
 long_boot=[]; long_pair=[]
 for _,row in wide_boot.iterrows():
  for metric in base.METRICS:
   value=row[metric]; long_boot.append({'replicate':int(row.replicate),'model':row.model,'metric_name':metric,'value':float(value) if np.isfinite(value) else np.nan,'undefined_reason':None if np.isfinite(value) else 'constant_or_single_class'})
 for _,row in wide_pair.iterrows():
  for metric in base.METRICS:
   value=row[metric]; long_pair.append({'replicate':int(row.replicate),'comparison':row.comparison,'metric':metric,'value':float(value) if np.isfinite(value) else np.nan,'undefined_reason':None if np.isfinite(value) else 'one_or_both_model_metrics_undefined'})
 apq(pd.DataFrame(long_boot),ROOT/'reports/bootstrap_metrics_v22.parquet'); acsv(pd.DataFrame(long_pair),ROOT/'reports/model_pairwise_differences_v22.csv')
 rows=[]; details={}
 for n in models:
  r=base.compute_metrics(pred.expert_label,pred[f'{n}_difficulty'],pred[f'{n}_class']); details[n]=r
  for metric in base.METRICS:
   g=wide_boot[wide_boot.model.eq(n)]; lo,hi,nv,w=base.ci_summary(g[metric]); rows.append({'model':n,'n_test':len(pred),'n_test_groups':pred.leakage_group_id.nunique(),'metric':metric,'point_estimate':r[metric],'ci_lower_95':lo,'ci_upper_95':hi,'n_bootstrap_valid':nv,'n_bootstrap_total':1000,'warning':w,'primary':metric=='kendall_tau_b'})
 for comp in ['D-A','D-B','D-C','D-E']:
  g=wide_pair[wide_pair.comparison.eq(comp)]
  for metric in base.METRICS:
   lo,hi,nv,w=base.ci_summary(g[metric]); rows.append({'model':comp,'n_test':len(pred),'n_test_groups':pred.leakage_group_id.nunique(),'metric':metric,'point_estimate':float(g[metric].mean()),'ci_lower_95':lo,'ci_upper_95':hi,'n_bootstrap_valid':nv,'n_bootstrap_total':1000,'warning':w,'primary':metric=='kendall_tau_b'})
 acsv(pd.DataFrame(rows),ROOT/'reports/benchmark_results_v22.csv'); aj(ROOT/'reports/benchmark_results_v22.json',{'stage':10,'cycle_version':'stage10_v2.2','status':'PASS','models':details,'rows':rows,'abstention_excluded_n':abstain,'comparator_metadata_sha256':{n:sha(ROOT/f'artifacts/stage10_comparators_v22/model_{n}_metadata.json') for n in ['A','B','C','E']},'bootstrap_undefined_reason_field':'undefined_reason','receipt_sha256':sha(ROOT/'reports/stage10_unseal_receipt_v22.json')})
 # Full and single-feature ablations plus the three estimable leave-one-out fits.
 abl=[]
 for name,src in [('Full','D'),('Feasibility-only','A'),('Precedent-only','B'),('Delta-SC-only','C')]: abl.append({'ablation':name,'source_model':src,'n_test':len(pred),**{m:details[src][m] for m in base.METRICS}})
 loo=[]
 for name,features in [('Full-Feasibility',['d_prec','d_sc']),('Full-Precedent',['d_feas','d_sc']),('Full-Delta-SC',['d_feas','d_prec'])]:
  mm=base.fit_model_features(dev,features); pp=mm.predict_frame(test,name.replace('-','_')); rr=base.compute_metrics(test.expert_label,pp.iloc[:,-1],pp.iloc[:,-2]); loo.append({'ablation':name,'features':features,'n_test':len(test),**{m:rr[m] for m in base.METRICS},'converged':mm.converged})
 acsv(pd.DataFrame(abl+loo),ROOT/'reports/ablation_results_v22.csv'); aj(ROOT/'reports/ablation_results_v22.json',{'stage':10,'cycle_version':'stage10_v2.2','status':'PASS','results':abl+loo,'leave_one_out':'PASS'})
 # Exact full-corpus precedent sensitivity.
 idx=base.ReactionPrecedentIndex(ROOT/'artifacts/reference_rxnfp.npy',ROOT/'artifacts/reference_metadata.parquet',ROOT/'artifacts/reference_nn_index.joblib',base.RXNFPRuntime(),top_k=10); allq=b.sort_values('reaction_hash',kind='mergesort').drop_duplicates('reaction_hash').reset_index(drop=True); vec=idx.runtime.embed_many(allq.reaction_smiles.astype(str).tolist()); sim=np.asarray(idx._reference_matrix,float)@np.asarray(vec,float).T; hashes=idx.metadata.reaction_hash.astype(str).to_numpy(); grid=[]; primary=allq.d_prec.to_numpy(float)
 for tau in [.75,.80,.85]:
  for n0 in [5,10,20]:
   vals=[]
   for j,row in enumerate(allq.itertuples(index=False)):
    ss=np.clip(sim[:,j],0,1); elig=hashes!=str(row.reaction_hash); smax=float(ss[elig].max()); na=int(np.count_nonzero(ss[elig]>=tau)); vals.append(1-(smax*(1-math.exp(-na/n0)) if na else 0.))
   col=f'dp_{tau}_{n0}'; allq[col]=vals; d2=allq[allq.split.eq('development')].copy(); t2=allq[allq.split.eq('locked_test')].copy(); mm=base.fit_model_features(d2.assign(d_prec=d2[col]),base.FEATURES); pp=mm.predict_frame(t2.assign(d_prec=t2[col]),'S'); rr=base.compute_metrics(t2.expert_label,pp.S_difficulty,pp.S_class); grid.append({'tau':tau,'N0':n0,'n_test':len(t2),**{x:rr[x] for x in base.METRICS}})
 stability=[]
 for tau in [.75,.80,.85]:
  for n0 in [5,10,20]:
   x=allq[f'dp_{tau}_{n0}'].to_numpy(float); y=primary; stability.append({'tau':tau,'N0':n0,'spearman_dp_vs_primary':float(spearmanr(x,y).statistic),'median_abs_change_dp':float(np.median(np.abs(x-y))),'q90_abs_change_dp':float(np.quantile(np.abs(x-y),.9)),'fraction_change_gt_0_10':float(np.mean(np.abs(x-y)>.1)),'fraction_change_gt_0_20':float(np.mean(np.abs(x-y)>.2))})
 acsv(pd.DataFrame(grid),ROOT/'reports/precedent_sensitivity_results_v22.csv'); aj(ROOT/'reports/precedent_sensitivity_results_v22.json',{'stage':10,'cycle_version':'stage10_v2.2','status':'PASS','grid_size':len(grid),'primary_tau':.8,'primary_N0':10,'results':grid,'feature_stability':stability})
 # Alternate SCScore definition with a separate reference-only ECDF and d_sc replacement during refit.
 ecdf,invalid=mean_ecdf(); raw=pd.read_parquet(ROOT/'data/processed/reaction_sc_raw.parquet').sort_values(['reaction_hash','route_id','step_id'],kind='mergesort').drop_duplicates('reaction_hash').set_index('reaction_hash'); dmean=[]
 for rh in allq.reaction_hash.astype(str):
  vals=json.loads(raw.loc[rh,'sc_precursor_values_json']); dmean.append(ecdf_right_continuous(ecdf,float(raw.loc[rh,'sc_product'])-float(np.mean(vals))))
 allq['d_sc_mean']=dmean; d2=allq[allq.split.eq('development')].copy(); t2=allq[allq.split.eq('locked_test')].copy(); mm=base.fit_model_features(d2.assign(d_sc=d2.d_sc_mean),base.FEATURES); pp=mm.predict_frame(t2.assign(d_sc=t2.d_sc_mean),'S'); rr=base.compute_metrics(t2.expert_label,pp.S_difficulty,pp.S_class); scres=[{'definition':'product_minus_max_precursor','model':'D_frozen','n_test':len(pred),**{x:details['D'][x] for x in base.METRICS}},{'definition':'product_minus_mean_precursor','model':'S_refit_development_only','n_test':len(t2),**{x:rr[x] for x in base.METRICS}}]; acsv(pd.DataFrame(scres),ROOT/'reports/scscore_sensitivity_results_v22.csv'); aj(ROOT/'reports/scscore_sensitivity_results_v22.json',{'stage':10,'cycle_version':'stage10_v2.2','status':'PASS','reference_valid_n':len(ecdf),'reference_invalid_n':invalid,'results':scres,'spearman_dsc_max_vs_mean':float(spearmanr(t2.d_sc,t2.d_sc_mean).statistic),'median_abs_change':float(np.median(np.abs(t2.d_sc.to_numpy(float)-t2.d_sc_mean.to_numpy(float))))})
 split=pd.read_parquet(ROOT/'data/splits/split_assignments.parquet'); refmeta=pd.read_parquet(ROOT/'artifacts/reference_metadata.parquet'); leak=base.audit_leakage(b,split,refmeta); aj(ROOT/'reports/leakage_audit_v22.json',{'stage':10,'cycle_version':'stage10_v2.2',**leak})
 outs=['data/benchmark/stage10_benchmark_reactions_v22.parquet','outputs/stage10_locked_test_predictions_v22.parquet','reports/benchmark_results_v22.csv','reports/benchmark_results_v22.json','reports/bootstrap_metrics_v22.parquet','reports/model_pairwise_differences_v22.csv','reports/ablation_results_v22.csv','reports/ablation_results_v22.json','reports/precedent_sensitivity_results_v22.csv','reports/precedent_sensitivity_results_v22.json','artifacts/sc_delta_mean_ecdf_stage10_v22.npz','reports/scscore_sensitivity_results_v22.csv','reports/scscore_sensitivity_results_v22.json','reports/leakage_audit_v22.json']
 man={'stage':10,'cycle_version':'stage10_v2.2','status':'PASS','created_at_utc':datetime.now(timezone.utc).isoformat(),'preanalysis_manifest_sha256':sha(ROOT/'reports/stage10_preanalysis_manifest_v22.json'),'preunseal_test_report_sha256':sha(ROOT/'reports/stage10_preunseal_test_report_v22.json'),'unseal_receipt_sha256':sha(ROOT/'reports/stage10_unseal_receipt_v22.json'),'locked_test_ids_sha256':sha(ROOT/'data/splits/test_ids_locked.txt'),'expert_labels_sha256':sha(ROOT/'data/labels/final_expert_labels.parquet'),'reaction_features_sha256':sha(ROOT/'data/processed/reaction_features.parquet'),'final_model_sha256':sha(ROOT/'artifacts/difficulty_model.pkl'),'final_model_metadata_sha256':sha(ROOT/'artifacts/difficulty_model_metadata.json'),'reference_corpus_sha256':sha(ROOT/'data/reference/reference_reactions_clean.parquet'),'reference_embeddings_sha256':sha(ROOT/'artifacts/reference_rxnfp.npy'),'primary_metric':'kendall_tau_b','secondary_metrics':['spearman_rho','macro_f1','balanced_accuracy','quadratic_weighted_kappa'],'bootstrap_method':'percentile','bootstrap_repetitions':1000,'bootstrap_unit':'leakage_group_id','bootstrap_seed':42,'precedent_parameter_grid':[[.75,5],[.75,10],[.75,20],[.8,5],[.8,10],[.8,20],[.85,5],[.85,10],[.85,20]],'scscore_primary_definition':'product_minus_max_precursor','scscore_alternate_definition':'product_minus_mean_precursor','abstention_excluded_n':abstain,'leave_one_out':'PASS','comparator_metadata_sha256':{n:sha(ROOT/f'artifacts/stage10_comparators_v22/model_{n}_metadata.json') for n in ['A','B','C','E']},'all_output_sha256':{p:sha(ROOT/p) for p in outs},'locked_test_modified':'NO','stage2_9_modified':'NO','stage11_started':'NO','test_set_tuning':'NO'}; aj(ROOT/'reports/stage10_manifest_v22.json',man); print(json.dumps({'status':'PASS','benchmark_rows':len(pred),'grid_results':len(grid),'abstention_excluded_n':abstain,'leave_one_out':'PASS','manifest':'reports/stage10_manifest_v22.json'},indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
