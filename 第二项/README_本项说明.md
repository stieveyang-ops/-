# 第二项 · 可运行作品（GitHub 公开发布版说明）

> 本目录是赛事材料"② 可运行作品"的分发版本：包含**原创代码、冻结科研资产、部署与运行脚本、
> 配置模板、文档与运行证据**。为满足 GitHub 的体积/单文件限制与第三方数据许可要求，
> 未包含运行时环境与第三方公开数据（见下表），**其余文件与交付包逐字节一致**。

## 一、本目录包含什么

| 类别 | 路径 | 说明 |
| --- | --- | --- |
| 原创代码 | `prospective_difficulty_tool\` | 图形界面、命令行入口、评分核心（前景难度推理与排序） |
| 原创代码 | `frozen_project\src\`、`frozen_project\scripts\` | 特征工程、前例检索、Stage 1–11 流水线脚本与 RXNFP 隔离工作进程 |
| 冻结科研资产 | `frozen_project\config\` | `config_production.yml`、`difficulty.yml`（特征顺序、阈值、排序规则） |
| 冻结科研资产 | `frozen_project\artifacts\` | 有序难度模型、SC 特征 ECDF、参考语料指纹与最近邻索引 |
| 冻结科研资产 | `frozen_project\data\` | 参考反应语料、标签与划分、特征中间产物 |
| 冻结科研资产 | `frozen_project\reports\` | Stage 5 / Stage 8 清单、环境检查报告等（含 25 项受保护资产哈希基线） |
| 启动与自检 | `启动_可运行作品.cmd`、`launch_gui.cmd`、`launch_gui.ps1`、`package_completeness_test.ps1`、`validate_environment.py` | 启动入口（含 UTF-8 编码护栏）与 fail-closed 自检 |
| 配置模板 | `portable_config.ps1`、`portable_config.example.ps1`、`requirements-portable-main.txt` | Python 路径配置与依赖版本锁定 |
| 环境重建 | `rebuild_rxnfp_environment.ps1`、`switch_to_local_rxnfp.ps1` | 重建/切换反应指纹独立运行时 |
| 运行产物 | `prospective_runs\` | 真实运行记录（含正常、边界、失败现场与示例 Dashboard） |
| 部署证据 | `local_deployment\` | 安装日志、修复前文件备份、来源记录 |
| 说明文档 | `README_中文部署说明.md`、`README_PORTABLE_DEPLOYMENT.md`、`本机使用说明.md`、`提交说明.md` | 部署、运行、故障处理与改动透明化记录 |

## 二、未包含的内容（及原因与替代方式）

| 未包含 | 原体量 | 原因 | 如何补齐 |
| --- | --- | --- | --- |
| `frozen_project\.conda-rxnfp\`（Python 3.8 + rxnfp 0.1.0 反应指纹运行时） | 1.66 GB / 26,863 个文件 | 环境不应进版本库；会让仓库文件数失控 | 运行 `rebuild_rxnfp_environment.ps1 -CondaExe "<你的conda.exe>"` 重建（该参数为必填），再执行 `switch_to_local_rxnfp.ps1`；详见 [`复现指南_REPRODUCE.md`](../复现指南_REPRODUCE.md) 第四节 |
| `external_public_data\`（USPTO 模型与模板、ZINC 库存） | 1.40 GB | `zinc_stock.hdf5` 为 1.27 GB，**超过 GitHub 单文件 100 MB 硬限**；且 ZINC 数据受其许可约束，不可再分发 | 见 [`复现指南_REPRODUCE.md`](../复现指南_REPRODUCE.md) 第三节：6 个文件的官方直链、字节数与 SHA-256 已全部给出并实测（HTTP 200、大小与包内一致），下载后用 `verify_public_data.py` 一键校验 |
| `__pycache__\` / `*.pyc` 等编译缓存 | 2,177 个文件 | 无信息价值，Python 自动重建 | 无需处理 |

## 三、跑起来需要什么

> **完整的分步指南见仓库根目录 [`复现指南_REPRODUCE.md`](../复现指南_REPRODUCE.md)（含全部官方数据直链、文件大小与 SHA-256）。**

```powershell
# 1) 主环境（Python 3.10.20）
conda create -n aizynth-portable python=3.10.20 -y
conda activate aizynth-portable
pip install -r requirements-portable-main.txt

# 2) 配置 python 路径（必做：仓库里的 portable_config.ps1 是作者本机路径）
Copy-Item portable_config.example.ps1 portable_config.ps1
notepad portable_config.ps1      # 把 $env:AIZYNTH_PYTHON 改成你的 python.exe 绝对路径

# 3) 反应指纹独立运行时（Python 3.8，约 1.7 GB）—— -CondaExe 为必填参数
powershell -NoProfile -ExecutionPolicy Bypass -File .\rebuild_rxnfp_environment.ps1 `
  -CondaExe "C:\你的Miniconda路径\Scripts\conda.exe"
powershell -NoProfile -ExecutionPolicy Bypass -File .\switch_to_local_rxnfp.ps1

# 4) 公开数据：6 个文件放入 external_public_data\public_data\（直链见复现指南）
python -m aizynthfinder.tools.download_public_data external_public_data\public_data
#    ⚠️ 该命令下载的 ZINC 库存是 2020 旧版（663 MB），本项目使用的是 1,339,073,560 字节版本：
#    https://ndownloader.figshare.com/files/54815918
python verify_public_data.py external_public_data\public_data   # 期望 6 项全部 OK

# 5) 自检（两项都必须是 PASS）并启动
. .\portable_config.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\package_completeness_test.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch_gui.ps1
```

在界面中输入目标分子 SMILES 与 Target ID，点击 `Run Search`，完成后会自动打开
`prospective_runs\<TargetID>_<时间戳>\prospective_dashboard.html`（含路线排序、逐反应难度与键线式结构图）。

## 四、方法与口径（简要）

- 逆合成路线由 **AiZynthFinder 4.4.1** 的 MCTS 搜索生成；
- 每条反应由冻结的三因子有序模型给出难度：`d_feas`（可行性）、`d_prec`（前例支持度）、`d_sc`（SCScore 变化分位）；
- 路线难度以**瓶颈步**为主：`bottleneck = max(d)`，另报 `mean` 与不确定性；
- 排序规则为字典序：`solved ↓ → bottleneck ↑ → mean ↑ → score ↓ → rank ↑ → route_id ↑`；
- 输出中的 `reaction_difficulty` 是**相对难度**，不代表实验成功率或产率。

## 五、第三方素材与许可

| 组件/数据 | 版本 | 许可 / 使用方式 |
| --- | --- | --- |
| AiZynthFinder | 4.4.1 | MIT，以依赖方式使用 |
| RDKit | 2023.9.6 | BSD-3-Clause |
| statsmodels / scikit-learn / NumPy / pandas / SciPy / PyArrow | 见 `requirements-portable-main.txt` | BSD / Apache-2.0 等 |
| ONNX Runtime | 1.23.2 | MIT |
| rxnfp（RXNFP 反应指纹） | 0.1.0 | MIT，独立进程调用 |
| USPTO 扩展策略模型与模板 | — | AiZynthFinder 官方发布物 |
| ZINC 砌块库存 | — | ZINC 许可，**不再分发** |
| Open Reaction Database（参考反应语料） | commit `05fe1a62` | CC-BY-SA-4.0，用于构建参考语料 |

## 六、独立完成声明

本作品由苏州大学 国际创新药学院 **施嘉仪（科学侧）**、**张睿阳（工程与智能体侧）** 独立完成，
未使用他人代码冒充原创；第三方组件与公开数据均以上表如实列明。
运行时环境由 **Agnes Harness（AGH）** 作为智能体运行时驱动完成开发与验证。
