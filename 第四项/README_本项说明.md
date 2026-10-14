# 第四项 · 运行与验证证据（GitHub 公开发布版说明）

> 本目录是赛事材料"④ 运行与验证证据"的完整内容：**任务执行记录、工具与设备调用链、
> 正常/边界/失败三类测试样例、学科匹配验证结果、全量 SHA-256 索引与 Agnes Harness 执行闭环证据**。
> 全部文件与交付包**逐字节一致**（已复核 476/476），证据索引 85 行哈希复算 **0 缺失、0 不符**。

## 一、目录结构

```
第四项/
├─ evidence_package/                      ← 成文证据
│  ├─ 01_任务执行记录.md                  ← 任务输入、执行步骤、结果与结论（含时间线）
│  ├─ 02_工具与设备调用链.md               ← 使用的工具/设备与调用顺序、参数与产物
│  ├─ 03_测试样例_正常_边界_失败.md         ← 三类样例的输入、期望、实际结果
│  ├─ 04_验证结果_学科匹配.md               ← 与本学科（药学/化学信息学）的匹配性验证
│  ├─ 05_证据索引与哈希.md                 ← 85 个证据文件的 SHA-256 索引（可逐行复算）
│  ├─ 06_AGH执行闭环证据索引.md             ← Agnes Harness 执行闭环的会话级证据说明
│  ├─ agh_sessions/
│  │  └─ AGH诊断包_会话1f119668_20261013.zip  ← AGH 官方诊断包（原始会话级证据）
│  ├─ runs/                              ← 7 个关键运行目录（正常/边界/失败现场）
│  ├─ environment_validation.json         ← 环境校验报告（PASS）
│  ├─ requirements-portable-main.txt      ← 依赖版本锁定
│  └─ _rebuild_hash_index.py              ← 索引重建脚本
├─ prospective_runs/                      ← 全部真实运行产物（逐个 Target 一个目录）
│  └─ <TargetID>_<时间戳>/
│     ├─ target.smi                       ← 输入
│     ├─ prospective_search_config.yml    ← 该次搜索的实际配置
│     ├─ aizynthfinder_search.log         ← 搜索日志
│     ├─ routes_raw.json                  ← 原始路线
│     ├─ scored_routes.csv/.json          ← 路线级难度与排序
│     ├─ scored_reactions.csv/.parquet    ← 反应级三因子与难度
│     ├─ reaction_diagrams/               ← 键线式结构图（png + svg）
│     ├─ prospective_dashboard.html       ← 结果页（可直接双击查看）
│     ├─ prospective_manifest.json        ← 产物清单与哈希
│     └─ prospective_blocker.json         ← 【失败现场】失败时的结构化原因（保留未删）
└─ 说明.txt                                ← 本目录内容与核对方式
```

## 二、三类测试样例（赛事要求的"正常、边界、失败"）

| 类别 | 对应运行目录 | 说明 |
| --- | --- | --- |
| 正常 | `fix_rxnfp_20261014`、`fix_verify_ethanol/aspirin/methanol_20261013`、`deployment_smoke_ethyl_benzoate_20261009` | 成功产出路线、反应评分与 Dashboard |
| 边界 | `evidence_methanol_20261013`、`evidence_minroutes0_20261013`（最小路线数参数为 0） | 可购买砌块直接命中、参数边界 |
| 失败 | `my_compound_007/008/0012_*`、`evidence_badparams_20261013` | 中文路径编码失败、参数非法等现场，**原样保留并如实报告**，修复后同类输入重跑成功 |

## 三、证据未被改动的核验方式（任何人可自行复算）

```powershell
cd 第四项
# 逐行比对 evidence_package/05_证据索引与哈希.md 中的 85 个 SHA-256
Get-Content .\evidence_package\05_证据索引与哈希.md |
  Select-String '^[0-9A-F]{64}' | ForEach-Object {
    $h, $rel = $_.Line -split '\s+', 2
    $p = $rel.Trim()
    if ((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash -ne $h) { "不符: $p" }
  }
```

索引说明：`05_证据索引与哈希.md` 与 `_rebuild_hash_index.py` 自身不在索引内，其余 85 个文件全部收录。

## 四、Agnes Harness（AGH）执行闭环证据

| 证据 | 位置 | 可核验内容 |
| --- | --- | --- |
| AGH 官方诊断包（会话 `1f119668`，2026-10-13 10:47–14:19） | `evidence_package\agh_sessions\` | 会话 ID、时间跨度、工具调用序列、验证信号与计划快照 |
| 闭环事实汇总 | `evidence_package\06_AGH执行闭环证据索引.md` | 3 个会话（`97c3d913` / `d7f34176` / `1f119668`）的时间线、419 次工具调用、770 条验证信号（762 通过 / 8 失败）、17 次计划快照、5 次修复决策 |

诊断包经检查**不含任何 API 密钥、令牌或个人信息**（仅含一份公开的作者邮箱）。

## 五、与其它材料的对应

- 本目录的 `prospective_runs\` 与第二项中的同名目录互为印证（第二项是可运行作品本体，本项是证据归档）；
- `evidence_package\03_测试样例_正常_边界_失败.md` 与演示视频中的异常处理片段相互对应；
- 冻结资产的 25 项受保护哈希基线在完整交付包的 `package_reference_sha256.csv` 中，可与之交叉复核。

---

苏州大学 国际创新药学院 · 施嘉仪（科学侧）· 张睿阳（工程与智能体侧）
运行时：Agnes Harness（AGH）
