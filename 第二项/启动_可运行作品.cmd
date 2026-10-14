@echo off
rem ============================================================================
rem  AIZynthFinder 反应难度前瞻性推理工具 —— 提交版启动入口
rem  本文件为「可运行作品」交付物新增，不修改原部署包内的任何文件。
rem  作用：设置 PYTHONUTF8=1 后，调用原包的 launch_gui.ps1。
rem
rem  为什么需要 PYTHONUTF8=1：
rem    若作品所在路径包含中文（例如 ...\黑客松\可运行作品\），
rem    工具生成的 prospective_search_config.yml 里会写入该中文路径（UTF-8 编码），
rem    而 AiZynthFinder 4.4.1 在中文 Windows 上以系统区域编码 cp936(GBK) 读取该文件，
rem    会抛出 UnicodeDecodeError: 'gbk' codec can't decode byte 0xae。
rem    设置 PYTHONUTF8=1 后，Python 以 UTF-8 读取配置文件，中文路径下可正常搜索。
rem    放在纯英文路径下（如 D:\aizynth_work\）则无此问题，无需本变量。
rem ============================================================================
setlocal
chcp 65001 > nul
set "PYTHONUTF8=1"
echo [可运行作品] PYTHONUTF8=1 已设置，正在启动 AIZynthFinder 反应难度工具...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_gui.ps1"
set "rc=%ERRORLEVEL%"
echo.
if "%rc%"=="0" (echo 工具已正常退出。) else (echo 启动或验证失败，退出码 %rc%。请查看 environment_validation.json 与 package_completeness_validation.log。)
pause
exit /b %rc%
