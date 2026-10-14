@echo off
rem ============================================================================
rem  AIZynthFinder 反应难度前瞻评分工具 —— 启动入口
rem  1) 设置 PYTHONUTF8=1（中文路径下 AiZynthFinder 以 GBK 读取 UTF-8 配置会报
rem     UnicodeDecodeError 并硬停止为 BLOCKED；该变量不改变任何模型/配置/冻结文件）
rem  2) 调用 launch_gui.ps1（内部先做环境校验，再打开图形界面）
rem  3) 若启动失败，窗口保持打开并显示错误原因，避免"一闪而过"
rem ============================================================================
setlocal
set "PYTHONUTF8=1"
chcp 65001 > nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_gui.ps1"
set "rc=%ERRORLEVEL%"
if not "%rc%"=="0" (
  echo.
  echo ============================================================
  echo  启动失败（退出码 %rc%）。
  echo  常见原因与处理：
  echo    1^) 环境校验未通过 —— 打开 environment_validation.json 查看 status 与 errors
  echo       或查看 package_completeness_validation.log；
  echo    2^) 首次运行被 Windows "安全警告" 拦住 —— 先双击
  echo       "解除文件锁定.cmd"，或右键本文件 - 属性 - 勾选"解除锁定"；
  echo    3^) 未找到 Python 环境 —— 按 README_中文部署说明.md 建好环境，
  echo       并在 portable_config.ps1 中填写 python.exe 路径。
  echo ============================================================
  echo.
  pause
)
exit /b %rc%
