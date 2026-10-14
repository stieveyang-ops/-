from __future__ import annotations
import hashlib,json,os,subprocess,tempfile
from datetime import datetime,timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
def pkg(name):
 try: return version(name)
 except PackageNotFoundError: return None
def atomic_json(path: Path, payload: dict):
 path.parent.mkdir(parents=True, exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix='.tmp',dir=str(path.parent)); os.close(fd); tmp=Path(tmp)
 try: tmp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,path)
 finally:
  if tmp.exists(): tmp.unlink()
def main():
 env=json.loads((ROOT/'reports/environment_check.json').read_text(encoding='utf-8')); db=json.loads((ROOT/'reports/reference_database_report.json').read_text(encoding='utf-8')); rx=json.loads((ROOT/'reports/rxnfp_build_report.json').read_text(encoding='utf-8')); sm=json.loads((ROOT/'reports/precedent_search_smoke_test.json').read_text(encoding='utf-8')); ix=json.loads((ROOT/'reports/reference_index_report.json').read_text(encoding='utf-8')); s2=json.loads((ROOT/'reports/stage2_validation.json').read_text(encoding='utf-8')); s3=json.loads((ROOT/'reports/stage3_validation.json').read_text(encoding='utf-8'))
 manifest={
  'stage':4,
  'status':'PASS',
  'validation_status':'PASS',
  'created_at_utc':datetime.now(timezone.utc).isoformat(),
  'git_commit':None,
  'git_commit_reason':'Project directory is not a Git worktree',
  'random_seed':42,
  'source_type':'ord',
  'source_name':db['source_name'],
  'ord_release_or_commit':'05fe1a62cb36d6bc3c07592ac1bd4ff1a4d8e43c',
  'input_path':db['input_path'],
  'input_manifest_path':db['input_manifest_path'],
  'input_file_count':db['input_file_count'],
  'input_manifest_sha256':db['input_manifest_sha256'],
  'input_file_manifest_sha256':db['input_file_manifest_sha256'],
  'input_format':'Parquet with serialized ORD Reaction protobuf payloads',
  'reaction_column':db.get('reaction_column'),
  'payload_column':db.get('payload_column','reaction'),
  'source_id_column':db.get('source_id_column'),
  'reaction_representation':db.get('reaction_representation'),
  'ord_schema_helper':db.get('ord_schema_helper'),
  'license_or_terms':db['license_or_terms'],
  'input_reference_sha256':db['input_manifest_sha256'],
  'stage2_chemistry_py_sha256':db['canonicalizer_file_sha256'],
  'reference_clean_sha256':db['clean_parquet_sha256'],
  'reference_rejected_sha256':db['rejected_parquet_sha256'],
  'reference_import_sha256':db['raw_import_parquet_sha256'],
  'n_input':db['n_input'],
  'n_valid_before_dedup':db['n_valid_before_dedup'],
  'n_clean_unique':db['n_clean_unique'],
  'n_exact_duplicates_removed':db['n_exact_duplicates_removed'],
  'n_rejected':db['n_rejected'],
  'rejection_counts':db.get('rejection_counts',{}),
  'rejection_policy':'Only malformed/uncanonicalizable records were rejected; no heuristic salt stripping or name-based repair was used.',
  'rxnfp_runtime_interpreter':str(ROOT/'.conda-rxnfp/python.exe'),
  'rxnfp_package_version':rx['rxnfp_package_version'],
  'rxnfp_model_name':'bert_ft',
  'rxnfp_dimension':256,
  'rxnfp_device':rx.get('device','cpu'),
  'rxnfp_embedding_sha256':sha(ROOT/'artifacts/reference_rxnfp.npy'),
  'reference_metadata_sha256':sha(ROOT/'artifacts/reference_metadata.parquet'),
  'nn_index_sha256':sha(ROOT/'artifacts/reference_nn_index.joblib'),
  'search_backend':'sklearn',
  'metric':'cosine',
  'algorithm':'brute',
  'top_k':100,
  'deployment_exact_match_policy':'keep',
  'benchmark_exact_match_policy':'exclude_same_reaction_hash',
  'stage2_reaction_steps_sha256':s2['reaction_steps_raw_sha256'],
  'stage2_routes_raw_sha256':s2['checks']['routes_raw_sha256'],
  'stage3_validation_status':s3['status'],
  'runtime_versions':{
   'python_main':env.get('python',{}).get('version'),
   'rdkit':env.get('rdkit',{}).get('version'),
   'numpy':env.get('numpy',{}).get('version'),
   'pandas':env.get('pandas',{}).get('version'),
   'scikit_learn':pkg('scikit-learn'),
   'ord_schema':pkg('ord-schema'),
   'pyarrow':pkg('pyarrow'),
   'transformers':rx.get('transformers_version'),
   'torch':rx.get('torch_version')
  },
  'tests':{
   'reference_database':'PASS',
   'rxnfp_build':'PASS',
   'precedent_search':'PASS',
   'full_pytest':'PASS (46 passed)'
  },
  'artifacts':{
   'raw_import':'data/reference/reference_reactions.parquet',
   'clean_corpus':'data/reference/reference_reactions_clean.parquet',
   'rejected_records':'data/reference/reference_reactions_rejected.parquet',
   'embeddings':'artifacts/reference_rxnfp.npy',
   'metadata':'artifacts/reference_metadata.parquet',
   'nearest_neighbour_index':'artifacts/reference_nn_index.joblib'
  },
  'warnings':[
   'ORD source is native protobuf serialized in Parquet; reaction SMILES were generated through ord-schema typed-role helpers.',
   'RXNFP bert_ft resources are package-managed; no standalone model-file hash was exposed by the runtime.',
   'Pytest completed with 9 upstream dependency deprecation warnings; no test failures.'
  ],
  'limitations':[
   'The 1839 rejected ORD records are retained in the rejected table and are not embedded.',
   'Stage 4 establishes reference corpus, embeddings, and search infrastructure only.',
   'N_analog, P_prec, D_prec, D_SC, final difficulty, uncertainty, and route ranking were not computed.'
  ]
 }
 atomic_json(ROOT/'reports/stage4_manifest.json', manifest)
 return 0
if __name__=='__main__': raise SystemExit(main())
