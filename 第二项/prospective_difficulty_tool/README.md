# 新化合物前瞻性推理工具

这是一个放在正式项目目录之外的独立工具。它不会修改
`aizynth-reaction-difficulty` 项目中的代码、配置、模型、reference corpus、
labels、locked-test 或 Stage 2–10 artifact。

## 最简单的用法

在 PowerShell 中执行：

```powershell
Set-Location "C:\Users\Pasem\Documents\Codex\2026-09-09\xia\prospective_difficulty_tool"

.\run_prospective_scoring.ps1 `
  -Smiles "YOUR_TARGET_SMILES" `
  -TargetId "my_compound_001"
```

例如（仅作为命令格式示例）：

```powershell
.\run_prospective_scoring.ps1 `
  -Smiles "CCOC(=O)c1ccccc1" `
  -TargetId "ethyl_benzoate_test"
```

默认输出目录是：

```text
D:\aizynth_prospective\<TargetId>\
```

如果 PowerShell 的执行策略阻止脚本，可以使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_prospective_scoring.ps1 `
  -Smiles "YOUR_TARGET_SMILES" `
  -TargetId "my_compound_001"
```

也可以显式指定外部输出目录：

```powershell
.\run_prospective_scoring.ps1 `
  -Smiles "YOUR_TARGET_SMILES" `
  -TargetId "my_compound_001" `
  -OutputDir "E:\prospective_results\my_compound_001"
```

## 工具自动完成的顺序

1. 用现有 AiZynthFinder 4.4.1、`config/config_production.yml`、`uspto` 和
   `zinc` 执行一次搜索；
2. 读取搜索产生的 `routes_raw.json`；
3. 对每个新反应步骤即时计算冻结的三个特征：
   `[d_feas, d_prec, d_sc]`；
4. 使用冻结的 Stage 8 OrderedModel 计算 `reaction_difficulty`、
   `uncertainty` 和 `confidence`；
5. 用冻结的 Stage 9 路线聚合和排序规则产生 `new_rank`；
6. 生成逐步骤结果、逐路线结果、审计 manifest 和可视化 HTML。

precedent 参数固定为 `tau=0.80`、`N0=10`、`metric=cosine`、`top_k=100`；
工具不提供修改这些参数的选项。

## 输出文件

```text
routes_raw.json              AiZynthFinder 原始路线
aizynthfinder_search.log     搜索日志
scored_reactions.parquet      逐反应步骤评分
scored_reactions.csv          逐反应步骤评分（表格软件可读）
scored_routes.json            逐路线评分、步骤和新排名
scored_routes.csv             逐路线摘要
prospective_dashboard.html    可视化结果（双击即可打开）
prospective_manifest.json     输入、输出、版本和 SHA256 审计
```

## 直接评分已有 routes JSON

如果已经在项目外部得到一个新目标的 AiZynthFinder `routes_raw.json`，可以
跳过搜索：

```powershell
& "E:\Anaconda\envs\aizynth\python.exe" -s .\prospective_score.py `
  --project-dir "C:\Users\Pasem\Documents\Codex\2026-09-09\xia\aizynth-reaction-difficulty" `
  --routes "D:\aizynth_prospective\my_compound_001\routes_raw.json" `
  --target-id "my_compound_001" `
  --output-dir "D:\aizynth_prospective\my_compound_001_scored"
```

## 如何查看结果

打开：

```text
D:\aizynth_prospective\<TargetId>\prospective_dashboard.html
```

可视化中：

- 路线按 `new_rank` 展示；
- 瓶颈难度越低，表示路线中最困难步骤越容易；
- 展开路线即可看到每一步的 `d_feas`、`d_prec`、`d_sc`、综合难度、
  不确定性和置信度；
- `reaction_difficulty` 不是产率，也不是实验成功概率。

如果出现 `BLOCKED`，请查看输出目录中的 `prospective_blocker.json`。工具会
停止，不会用替代模型、随机权重或修改冻结文件来继续。
## 本次运行独立调整搜索参数

搜索参数只对当前 prospective run 生效。工具会把正式配置读入内存，在本次输出目录写入 `prospective_search_config.yml`，并在 manifest 中记录两个配置文件的 SHA256；正式项目配置不会被覆盖。

```powershell
.\run_prospective_scoring.ps1 `
  -Smiles "CCOC(=O)c1ccccc1" `
  -TargetId "ethyl_benzoate_custom" `
  -IterationLimit 200 `
  -TimeLimit 120 `
  -MaxTransforms 6 `
  -MaxRoutes 10 `
  -MinRoutes 3
```

参数含义：`IterationLimit` 是 MCTS 轮数上限，`TimeLimit` 是秒数，`MaxTransforms` 是路线最大反应步数，`MaxRoutes` 是最多显示路线，`MinRoutes` 是最少请求路线（不能大于 `MaxRoutes`）。

## 键线式输出

每条唯一反应步骤会在输出目录的 `reaction_diagrams` 子目录生成 `<reaction_hash>.svg` 和 `<reaction_hash>.png`。SVG 会嵌入 `prospective_dashboard.html`，图中显示所有 precursor、反应箭头和 product。CSV/Parquet 仍保留原始 `reaction_smiles`、`precursor_smiles` 和 `product_smiles`；无法无歧义绘图时，具体原因会写入 manifest 的 `diagram_warnings`，不会猜测或改写结构。

## 桌面图形界面

桌面上已创建 `AiZynthFinder Prospective Tool.lnk`。双击后可直接：

1. 输入新的目标分子 SMILES 和 Target ID；
2. 调整 MCTS 轮数、时间限制、最大反应步数、最多路线和最少路线；
3. 点击 `RUN SEARCH AND SHOW ROUTES`；
4. 在窗口中查看路线排名、难度、置信度和逐步 SMILES；
5. 自动打开同一运行目录中的 HTML 报告，其中包含 RDKit 键线式。

每次运行使用新的时间戳输出目录，不覆盖旧结果。GUI 只是调用本目录的独立 `prospective_score.py`，不会修改正式项目配置或 Stage 1–11 文件。
