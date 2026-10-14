# 复现结果对照表（Reproduction Baseline）

> **用途**：第三方按 [`复现指南_REPRODUCE.md`](复现指南_REPRODUCE.md) 跑完后，用本表比对 **路线数、步骤数、难度区间与置信度** 是否落在同一量级。
> **数据来源**：`第四项/prospective_runs/` 中归档的真实运行产物（成功运行内附 `prospective_manifest.json`）。
> **重要**：MCTS 搜索是随机过程，**同参数下结果相近但不逐位相同**；只有固定随机种子时才会逐位复现。

- 归档运行目录：**24** 个 —— 成功 **16**、边界/失败 **8**
- 共用评分口径：`q33 = 0.3005421128682305`、`q67 = 0.5006582129614043`，特征顺序 `d_feas, d_prec, d_sc`，前例检索 `cosine, tau=0.8, N0=10, top_k=100`，路线排序为字典序 `solved↓ → bottleneck↑ → mean↑ → score↓ → rank↑ → route_id↑`
- 难度为 **0–100 的相对分数**，不是实验成功率或产率；低证据样本按冻结阈值标为 `low`，属预期行为。

## 一、成功运行（status = PASS）

| # | 运行目录 | Target ID | 目标 SMILES | 路线数 | 已解出 | 零步路线 | 唯一反应数 | 搜索参数 迭代/秒/步数/路线/最少 | 瓶颈难度 | 平均难度 | 不确定性 | 置信度 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `deployment_smoke_ethyl_benzoate_20261009_092047` | `deployment_smoke_ethyl_benzoate_20261009_092047` | `CCOC(=O)c1ccccc1` | 3 | 3 | 0 | 3 | 30/45.0/6/3/1 | 49.31–52.24 | 49.31–52.24 | 0.083–0.500 | high/medium |
| 2 | `evidence_caffeic_20261013` | `evidence_caffeic_20261013` | `O=C(O)/C=C/c1ccc(O)c(O)c1` | 10 | 10 | 0 | 10 | 100/120.0/6/10/3 | 49.67–52.21 | 49.67–52.21 | 0.089–1.000 | high/low |
| 3 | `evidence_methanol_20261013` | `evidence_methanol_20261013` | `CO` | 1 | 0 | 1 | 0 | 100/120.0/6/10/3 | — | — | — | not_applicable |
| 4 | `fix_move_smoke_ethanol_20261013` | `fix_move_smoke_ethanol` | `CCO` | 5 | 5 | 0 | 5 | 100/120.0/6/10/3 | 49.37–50.24 | 49.37–50.24 | 0.540–0.949 | low |
| 5 | `fix_verify_aspirin_20261013` | `fix_verify_aspirin` | `CC(=O)Oc1ccccc1C(=O)O` | 6 | 6 | 0 | 6 | 100/120.0/6/10/3 | 49.22–52.43 | 49.22–52.43 | 0.331–0.884 | low/medium |
| 6 | `fix_verify_ethanol_20261013` | `fix_verify_ethanol` | `CCO` | 5 | 5 | 0 | 5 | 100/120.0/6/10/3 | 49.37–50.24 | 49.37–50.24 | 0.540–0.949 | low |
| 7 | `fix_verify_methanol_20261013` | `fix_verify_methanol` | `CO` | 1 | 0 | 1 | 0 | 100/120.0/6/10/3 | — | — | — | not_applicable |
| 8 | `my_compound_0013_20261013_091224` | `my_compound_0013` | `CC(=O)Oc1ccccc1C(=O)O` | 6 | 6 | 0 | 6 | 100/120.0/6/10/3 | 49.22–52.43 | 49.22–52.43 | 0.331–0.884 | low/medium |
| 9 | `my_compound_0014_20261013_094431` | `my_compound_0014` | `NNc1ccc([N+](=O)[O-])cc1[N+](…` | 10 | 10 | 0 | 13 | 100/120.0/6/10/3 | 49.91–50.27 | 49.45–49.96 | 0.662–1.000 | low |
| 10 | `my_compound_0016_20261013_112820` | `my_compound_0016` | `O=C(O)/C=C/c1ccc(O)c(O)c1` | 10 | 10 | 0 | 10 | 100/120.0/6/10/3 | 49.67–52.21 | 49.67–52.21 | 0.089–1.000 | high/low |
| 11 | `my_compound_0018_20261014_002148` | `my_compound_0018` | `NNc1nnc(NN)nn1` | 4 | 0 | 0 | 17 | 100/120.0/10/15/4 | 50.24–50.27 | 49.52–49.91 | 0.728–0.847 | low |
| 12 | `my_compound_003_20261013_133423` | `my_compound_003` | `CC(=O)Oc1ccccc1C(=O)O` | 6 | 6 | 0 | 6 | 100/120.0/6/10/3 | 49.22–52.43 | 49.22–52.43 | 0.331–0.884 | low/medium |
| 13 | `my_compound_004_20261009_092551` | `my_compound_004` | `CC(=O)Oc1ccccc1C(=O)O` | 6 | 6 | 0 | 6 | 100/120.0/6/10/3 | 49.22–52.43 | 49.22–52.43 | 0.331–0.884 | low/medium |
| 14 | `my_compound_004_20261013_143641` | `my_compound_004` | `O=C(O)/C=C/c1ccc(O)c(O)c1` | 10 | 10 | 0 | 10 | 100/120.0/6/10/3 | 49.67–52.21 | 49.67–52.21 | 0.089–1.000 | high/low |
| 15 | `my_compound_005_20261009_102206` | `my_compound_005` | `CC(=O)Oc1ccc(NC(=O)CCC(=O)O)c…` | 3 | 3 | 0 | 3 | 100/120.0/6/10/3 | 49.49–49.71 | 49.49–49.71 | 0.877–0.999 | low |
| 16 | `示例结果_苯甲酸乙酯_20261013` | `utf8_probe_20261013` | `CCOC(=O)c1ccccc1` | 5 | 5 | 0 | 5 | 100/60.0/5/5/2 | 49.26–52.24 | 49.26–52.24 | 0.083–0.815 | high/low/medium |

## 二、边界与失败现场（同样保留，用于核对异常处理行为）

| 运行目录 | 状态 | 记录的原因 |
| --- | --- | --- |
| `evidence_badparams_20261013` | BLOCKED | ProspectiveBlocked: min-routes/max-routes must satisfy 0 <= min_routes <= max_routes |
| `evidence_badsmiles_20261013` | 无 blocker | 进程在写出 blocker 前退出（目录仅含少量中间文件） |
| `evidence_minroutes0_20261013` | BLOCKED | ProspectiveBlocked: AiZynthFinder search failed with return code 1: Loading template-based expansion policy mo |
| `my_compound_0012_20261013_082337` | BLOCKED | ProspectiveBlocked: AiZynthFinder search failed with return code 1: Traceback (most recent call last):   File  |
| `my_compound_003_20261013_133212` | 无 blocker | 进程在写出 blocker 前退出（目录仅含少量中间文件） |
| `my_compound_003_20261013_133220` | 无 blocker | 进程在写出 blocker 前退出（目录仅含少量中间文件） |
| `my_compound_007_20261013_015740` | BLOCKED | ProspectiveBlocked: AiZynthFinder search failed with return code 1: Traceback (most recent call last):   File  |
| `my_compound_008_20261013_022205` | BLOCKED | ProspectiveBlocked: AiZynthFinder search failed with return code 1: Traceback (most recent call last):   File  |

失败现场的价值：证明工具在异常输入/非法参数下**硬停止且不产出伪结果**（fail-closed），对应赛事要求的『异常处理』环节；详见 `第四项/evidence_package/03_测试样例_正常_边界_失败.md`。

## 三、如何比对你的复现结果

```powershell
# 1) 复现表 1 号运行为例（苯甲酸乙酯，参数与归档一致）
powershell -NoProfile -ExecutionPolicy Bypass -File .\prospective_difficulty_tool\run_prospective_scoring.ps1 `
  -Smiles "CCOC(=O)c1ccccc1" -TargetId "repro_ethyl_benzoate" `
  -IterationLimit 100 -TimeLimit 60 -MaxTransforms 5 -MaxRoutes 5 -MinRoutes 2

# 2) 看关键结果
$m = Get-Content .\prospective_runs\repro_ethyl_benzoate*\prospective_manifest.json -Raw | ConvertFrom-Json
$m.status; $m.counts; $m.search_parameters
Import-Csv .\prospective_runs\repro_ethyl_benzoate*\scored_routes.csv |
  Select-Object route_id, solved, number_of_reactions, difficulty_bottleneck, difficulty_mean, route_confidence
```

**判定标准**

1. `status = PASS`，且 `route_count ≥ min_routes`；
2. `difficulty_bottleneck` / `difficulty_mean` 与上表同目标分子落在相近区间（同一实现下通常相差 < 5 分）；
3. `reaction_unique_count` 与路线数同量级；`route_confidence` 分档与 q33/q67 阈值一致；
4. 若路线数明显偏少：先确认公开数据版本（`python verify_public_data.py`，6 项应全 OK）与冻结资产哈希（`package_reference_sha256.csv`，25 项应全匹配）。

## 四、说明

- 表中『瓶颈难度』 = 各路线 `bottleneck = max(d)` 的最小/最大值；『平均难度』 = 各路线 `mean` 的最小/最大值；不确定性 = 路线级 `U = max(U_step)`。
- 归档运行的环境版本：Python 3.10.20 / AiZynthFinder 4.4.1 / RDKit 2023.9.6 / NumPy 1.26.4 / pandas 2.3.3 / statsmodels 0.14.4 / scikit-learn 1.5.2 / ONNX Runtime 1.23.2（各 manifest 的 `runtime` 字段）。
- 每次运行的完整产物（含 Dashboard、键线式结构图、产物清单与哈希）都在各自的运行目录内，可直接打开核对。

