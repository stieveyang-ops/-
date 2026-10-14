# 新电脑部署说明

本目录是可复制到不同磁盘、不同目录、不同 Windows 电脑的部署包。运行时不需要原电脑上的项目路径，也不会修改或重新计算 Stage 1-11 科研文件。

## 需要你在新电脑上完成的操作

1. 将整个 `AIZynthFinder_Reaction_Difficulty_Portable_2026-10-08_v2` 文件夹复制到目标电脑，不能只复制其中一部分。
2. 在目标电脑安装 Conda/Miniconda，并建立一个可写的 Python 3.10.20 环境。主环境所需版本见 `requirements-portable-main.txt`。禁止使用 `pip --user`，禁止用其他版本模型或随机权重替代。
3. 将 `portable_config.example.ps1` 复制为 `portable_config.ps1`，只修改其中的 Python 路径，例如：

   ```powershell
   $env:AIZYNTH_PYTHON = "C:\Tools\CondaEnvs\aizynth-portable\python.exe"
   ```

4. 在部署包根目录执行完整度和环境验证：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\package_completeness_test.ps1
   ```

5. 只有以下两个文件都显示 `PASS` 时才可以继续：
   - `package_completeness_report.json`
   - `environment_validation.json`
6. 双击 `launch_gui.cmd` 启动图形界面。输入 SMILES、Target ID，设置轮数、时间、最大反应步数和路线数，然后点击 `RUN SEARCH AND SHOW ROUTES`。

## 中文路径下的 BLOCKED 问题（已于 2026-10-13 修复）

若部署路径含中文，AiZynthFinder 4.4.1 以进程区域编码读取 YAML 配置时会失败（`UnicodeDecodeError: 'gbk' codec can't decode byte 0xae`），工具按硬停止规则报 `BLOCKED`。

三个入口（`launch_gui.cmd`、`launch_gui.ps1`、`prospective_difficulty_tool\run_prospective_scoring.ps1`）现在均自动设置 `PYTHONUTF8=1`，子进程逐级继承，无需手工配置，也不涉及模型、配置或冻结文件的改动。如需回到修复前版本，备份在 `local_deployment\pre_20261013_fix_*.ps1|*.cmd`。将部署包放在纯英文路径下可完全避免该问题。

## RXNFP 在新电脑上不能运行时

复制的 `frozen_project\.conda-rxnfp` 可能带有原电脑的 Conda 前缀。如果验证报告显示 RXNFP 失败，请保留原目录，不要覆盖或删除，然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\rebuild_rxnfp_environment.ps1 `
  -CondaExe "C:\你的Conda路径\conda.exe"
```

脚本会新建 `.conda-rxnfp-local`。完成后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\switch_to_local_rxnfp.ps1
```

随后必须重新运行 `package_completeness_test.ps1`，并确认真实 RXNFP 输出为 `(1, 256)`、所有数值 finite、最终状态为 `PASS`。

## 停止条件

如果验证状态为 `BLOCKED`、关键文件 SHA256 不一致、依赖版本不一致、OrderedModel 无法导入或 RXNFP 验证失败，必须停止。不得修改冻结科研文件、替换模型、使用随机权重或绕过验证。

历史 reports 中出现的原电脑绝对路径属于 Stage 审计证据，不是当前运行路径，不应修改。实际运行入口会按部署包当前位置解析模型、库存、配置和输出目录。

更完整的环境安装示例、CLI 用法和科学边界见 `README_PORTABLE_DEPLOYMENT.md`。
