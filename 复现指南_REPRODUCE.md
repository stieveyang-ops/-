# 复现指南（Reproduce from scratch）

> 本指南面向**从零开始的第三方**：只需一台 Windows 电脑 + 网络，即可把本仓库的内容跑起来并复现结果。
> 全部步骤均已在本项目上实测；涉及第三方数据的地方都给出了**官方来源、精确文件大小与 SHA-256**，可逐项核对。

- 预计磁盘占用：主环境约 3 GB，反应指纹独立运行时约 1.7 GB，公开数据约 1.47 GB
- 预计耗时：环境 15–30 分钟 + 数据下载时间（ZINC 库存 1.34 GB）
- 不需要 GPU；全部推理在 CPU 完成

---

## 一、为什么仓库里没有数据和运行时环境

| 内容 | 体量 | 是否随仓库分发 | 原因 |
| --- | --- | --- | --- |
| 运行时环境 `frozen_project/.conda-rxnfp/` | 约 1.7 GB / 26,863 个文件 | ❌ | 环境不应进版本库；本仓库提供一键重建脚本 |
| 第三方公开数据 `external_public_data/` | 约 1.47 GB | ❌ | 超过 GitHub 单文件 100 MB 硬限；ZINC 库存受其许可约束，不宜再分发 |
| 团队自有代码、配置、冻结模型与科研资产 | 约 37 MB | ✅ | 见 `第二项/` |

---

## 二、第 1 步：主环境（Python 3.10）

```powershell
# 1) 安装 Miniconda 后，创建主环境
conda create -n aizynth-portable python=3.10.20 -y
conda activate aizynth-portable

# 2) 安装锁定版本依赖（在 第二项\ 目录下执行）
cd 第二项
pip install -r requirements-portable-main.txt

# 3) 告诉启动器你的 python 路径（把 example 复制为正式配置后编辑）
Copy-Item portable_config.example.ps1 portable_config.ps1
notepad portable_config.ps1      # 将 $env:AIZYNTH_PYTHON 改为你的 python.exe 绝对路径
```

> `portable_config.ps1` 里默认写的是作者本机的路径，**必须改成你自己的**，例如
> `$env:AIZYNTH_PYTHON = "C:\Tools\CondaEnvs\aizynth-portable\python.exe"`。
> 禁止使用 `pip --user`，禁止替换为其它版本模型或随机权重。

## 三、第 2 步：公开数据（6 个文件，全部为官方来源）

在 `第二项\` 目录下创建 `external_public_data\public_data\`，把下列 6 个文件下载进去（文件名必须完全一致）：

| 文件名 | 用途 | 官方来源 | 直链 | 字节数 | SHA-256 前 16 位 |
| --- | --- | --- | --- | --- | --- |
| `uspto_model.onnx` | USPTO 扩展策略模型（ONNX） | Zenodo 7797465（AiZynthFinder 官方发布） | [zenodo.org/record/7797465/files/uspto_model.onnx…](https://zenodo.org/record/7797465/files/uspto_model.onnx) | 91,518,243 | `BD0A3CB74CD7068D…` |
| `uspto_filter_model.onnx` | 快速过滤模型（ONNX，cutoff 0.05） | Zenodo 7797465 | [zenodo.org/record/7797465/files/uspto_filter_model.onnx…](https://zenodo.org/record/7797465/files/uspto_filter_model.onnx) | 16,788,859 | `AD29AA32BDFCBE37…` |
| `uspto_ringbreaker_model.onnx` | RingBreaker 扩展策略模型（ONNX） | Zenodo 7797465 | [zenodo.org/record/7797465/files/uspto_ringbreaker_model.on…](https://zenodo.org/record/7797465/files/uspto_ringbreaker_model.onnx) | 15,036,094 | `1BF0690352D9E921…` |
| `uspto_templates.csv.gz` | USPTO 反应模板库（下载后需重命名为 uspto_templates.csv.gz） | Zenodo 7341155 | [zenodo.org/record/7341155/files/uspto_unique_templates.csv…](https://zenodo.org/record/7341155/files/uspto_unique_templates.csv.gz) | 3,313,598 | `A4F1945E90CFA195…` |
| `uspto_ringbreaker_templates.csv.gz` | RingBreaker 模板库（下载后需重命名为 uspto_ringbreaker_templates.csv.gz） | Zenodo 7341155 | [zenodo.org/record/7341155/files/uspto_ringbreaker_unique_t…](https://zenodo.org/record/7341155/files/uspto_ringbreaker_unique_templates.csv.gz) | 373,753 | `5616A056454B10A2…` |
| `zinc_stock.hdf5` | ZINC 可购化合物库存（1,339,073,560 字节版本） | Figshare 文章 29145899「zincstock for aizynthfinder」DOI 10.6084/m9.figshare.29145899.v1 | [ndownloader.figshare.com/files/54815918…](https://ndownloader.figshare.com/files/54815918) | 1,339,073,560 | `FF54C334C3DFC118…` |

### 方式 A（最快，推荐）：从本仓库 Release 直接下载

作者已把 6 个文件按**逐字节一致的版本**打包为 Release 附件（下载后可直接用校验脚本核对）：

| 内容 | 链接 |
| --- | --- |
| 数据包（557.2 MB） | <https://github.com/stieveyang-ops/-/releases/download/v1.0-data/ProRetro-Agent_public_data_v1.zip> |
| Release 页面 | <https://github.com/stieveyang-ops/-/releases/tag/v1.0-data> |

- 附件 SHA-256 = `7C64CC6DCF7F8853CF4907B1056721A720859E7A579DD8EBE115EB512B94E7A0`（584,303,731 字节）；解压后得到 `public_data/` 目录
- 把其中 6 个文件放入 `external_public_data\public_data\`，再运行 `python verify_public_data.py external_public_data\public_data`，期望 6 项全部 `[OK]`

### 方式 B：用 AiZynthFinder 自带命令下载 5 个模型/模板

```powershell
# AiZynthFinder 的官方下载命令（写入目标目录）
python -m aizynthfinder.tools.download_public_data external_public_data\public_data
```

⚠️ **注意**：该命令会把 `uspto_unique_templates.csv.gz` / `uspto_ringbreaker_unique_templates.csv.gz` 分别保存为
`uspto_templates.csv.gz` / `uspto_ringbreaker_templates.csv.gz`（正确），但它下载的 **ZINC 库存是 2020 年的旧版**
（`zinc_stock_17_04_20.hdf5`，663,232,280 字节，figshare 文件 23086469），**与本项目使用的版本不同**。
因此 ZINC 库存请务必用下表直链单独下载（1,339,073,560 字节）。

### 方式 C：逐个直链下载（官方源，最稳）

```powershell
# 5 个模型/模板（Zenodo，AiZynthFinder 官方发布）
Invoke-WebRequest "https://zenodo.org/record/7797465/files/uspto_model.onnx" -OutFile external_public_data\public_data\uspto_model.onnx
Invoke-WebRequest "https://zenodo.org/record/7797465/files/uspto_filter_model.onnx" -OutFile external_public_data\public_data\uspto_filter_model.onnx
Invoke-WebRequest "https://zenodo.org/record/7797465/files/uspto_ringbreaker_model.onnx" -OutFile external_public_data\public_data\uspto_ringbreaker_model.onnx
Invoke-WebRequest "https://zenodo.org/record/7341155/files/uspto_unique_templates.csv.gz" -OutFile external_public_data\public_data\uspto_templates.csv.gz
Invoke-WebRequest "https://zenodo.org/record/7341155/files/uspto_ringbreaker_unique_templates.csv.gz" -OutFile external_public_data\public_data\uspto_ringbreaker_templates.csv.gz

# ZINC 库存（本项目使用的确切版本：1,339,073,560 字节）
Invoke-WebRequest "https://ndownloader.figshare.com/files/54815918" -OutFile external_public_data\public_data\zinc_stock.hdf5
```

### 校验下载结果（强烈建议）

```powershell
python verify_public_data.py external_public_data\public_data
# 期望输出：6 项全部 [OK]
```

完整 SHA-256 基准（与 `package_reference_sha256.csv` 中 25 项受保护资产一致）：

| 文件名 | 字节数 | SHA-256 |
| --- | --- | --- |
| `uspto_model.onnx` | 91,518,243 | `BD0A3CB74CD7068DE474C8FB789A00A66BC42C75636D66510CCAC585EBE928F8` |
| `uspto_filter_model.onnx` | 16,788,859 | `AD29AA32BDFCBE37065045546493806CF04899C55386C438905D83FB14BB6320` |
| `uspto_ringbreaker_model.onnx` | 15,036,094 | `1BF0690352D9E9212D7DBE8B35649CAF74F73EF0B30EDEFDFDAC37FCE38085BE` |
| `uspto_templates.csv.gz` | 3,313,598 | `A4F1945E90CFA195538320833D68AED38F14E2FCC2F8AFB5D958BC920EDCAFBE` |
| `uspto_ringbreaker_templates.csv.gz` | 373,753 | `5616A056454B10A2F044E69E027422128986856EBD958541A3BF9F837E3A0D14` |
| `zinc_stock.hdf5` | 1,339,073,560 | `FF54C334C3DFC11882D5FA3024FDE3BE8CF3E38F979D93A39B9BE8CCA1A5DC85` |

## 四、第 3 步：反应指纹独立运行时（Python 3.8 + rxnfp）

```powershell
# 在 第二项\ 目录下执行；-CondaExe 是必填参数，指向你的 conda.exe
powershell -NoProfile -ExecutionPolicy Bypass -File .\rebuild_rxnfp_environment.ps1 `
  -CondaExe "C:\你的Miniconda路径\Scripts\conda.exe"

# 脚本会新建 frozen_project\.conda-rxnfp-local（不会覆盖任何已有目录），随后切换启用
powershell -NoProfile -ExecutionPolicy Bypass -File .\switch_to_local_rxnfp.ps1
```

脚本依据 `frozen_project\requirements-rxnfp-lock.txt` 安装锁定版本（Python 3.8.20 + rxnfp 0.1.0 等）。

## 五、第 4 步：自检（fail-closed，必须两项都 PASS）

```powershell
. .\portable_config.ps1          # 让脚本读到你的 python 路径
powershell -NoProfile -ExecutionPolicy Bypass -File .\package_completeness_test.ps1
```

必须同时满足：

| 检查项 | 期望 |
| --- | --- |
| `package_completeness_report.json` | `"status": "PASS"`（28 项必需文件齐全、25 项受保护资产 SHA-256 全部匹配、无禁用目录） |
| `environment_validation.json` | `"status": "PASS"`，且 `rxnfp.status = "PASS"`、`shape = [1, 256]`、`finite = true` |

任一项为 `BLOCKED` 时**不要继续**：错误原因写在 `package_completeness_validation.log` 与 `environment_validation.json` 的 `errors` 字段中。

## 六、第 5 步：运行并复现结果

```powershell
# 图形界面
.\启动_可运行作品.cmd

# 或命令行（示例：咖啡酸）
powershell -NoProfile -ExecutionPolicy Bypass -File .\prospective_difficulty_tool\run_prospective_scoring.ps1 `
  -Smiles "O=C(O)/C=C/c1ccc(O)c(O)c1" -TargetId "repro_caffeic" `
  -IterationLimit 100 -TimeLimit 120 -MaxTransforms 6 -MaxRoutes 10 -MinRoutes 3
```

输出目录：`prospective_runs\<TargetID>_<时间戳>\`，其中：

| 文件 | 内容 |
| --- | --- |
| `prospective_dashboard.html` | 结果页（路线排序、逐反应难度与三因子、键线式结构图），双击即可用浏览器打开 |
| `scored_routes.csv` / `.json` | 路线级：解出与否、步数、瓶颈难度、平均难度、不确定性、置信度 |
| `scored_reactions.csv` / `.parquet` | 反应级：`d_feas` / `d_prec` / `d_sc` / `reaction_difficulty` |
| `routes_raw.json` | AiZynthFinder 原始搜索输出 |
| `prospective_manifest.json` | 本次运行的配置、冻结资产哈希与产物清单 |

命令行结束时打印的 JSON 中 `"status": "PASS"` 表示该次运行成功。仓库 `第四项/prospective_runs/` 内有历史运行产物可用于对照（含正常、边界与失败三类）。

## 七、常见问题（都会导致硬停止，按此排查）

| 现象 | 原因与处理 |
| --- | --- |
| 自检报 `Missing required file: external_public_data/...` | 数据未放齐或文件名不符；用第 3 步的直链重新下载并运行 `verify_public_data.py` |
| 自检报 `受保护资产 SHA256 不一致`（仅 zinc_stock.hdf5） | 你下载的是 2020 旧版库存（663 MB）。请改用 `https://ndownloader.figshare.com/files/54815918`（1,339,073,560 字节） |
| `environment_validation.json` 中 `rxnfp.status = FAIL` | 反应指纹运行时未重建或未切换；执行第 4 步的 `rebuild_rxnfp_environment.ps1` 与 `switch_to_local_rxnfp.ps1` |
| 启动时报 `No Python environment was found` | `portable_config.ps1` 里的 `$env:AIZYNTH_PYTHON` 未改成你的路径 |
| 路径含中文时出现 `UnicodeDecodeError: 'gbk' codec can't decode ...` | 三个启动入口已内置 `PYTHONUTF8=1`；若自行编写调用脚本，请显式设置该变量，或把整包放在纯英文路径下 |
| 双击脚本弹出"无法验证发布者" | Windows 对无签名脚本的常规提示（非故障）：右键文件 → 属性 → 勾选"解除锁定"，或直接点"运行(R)" |
| 搜索报 `PermissionError ... portable_rxnfp_check_... / prospective_rxnfp_...` | 某些安全策略禁止该解释器写入系统临时目录；本项目已把临时目录改到包内 `_runtime_tmp\`（详见 `第二项/本机使用说明.md`） |

## 八、复现判定标准（怎样算复现成功）

1. `package_completeness_report.json` 与 `environment_validation.json` 均为 `PASS`；
2. 命令行/界面运行任一目标分子，得到 `status: PASS` 与不少于 1 条路线；
3. 打开 `prospective_dashboard.html` 能看到路线排序与逐反应难度（含 `d_feas` / `d_prec` / `d_sc`）；
4. 与仓库 `第四项/prospective_runs/` 中的历史产物对照，同一目标分子与同一参数下路线数量级与难度区间一致（搜索为随机过程，逐位一致仅在同种子下成立）。

> 科学边界：`reaction_difficulty` 是**相对难度**，不代表实验成功率或产率。锁定测试集上只有单因子 D_F 达到统计显著（Kendall τ_b = +0.269，p = 0.020），三因子冻结模型未获证据支持（−0.034，p = 0.765）——该负面结果已如实记录在 `第一项/01_项目说明.docx` 与 `第四项/evidence_package/04_验证结果_学科匹配.md` 中。
