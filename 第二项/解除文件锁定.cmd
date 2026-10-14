@echo off
rem ============================================================================
rem  一键解除文件锁定（移除 Windows“网络来源”标记 / Mark of the Web）
rem  作用：消除双击脚本时出现的“打开文件 - 安全警告 / 无法验证发布者”提示。
rem  说明：仅删除文件的 Zone.Identifier 备用数据流，不修改任何文件内容，
rem        不影响哈希校验结果。
rem ============================================================================
setlocal
set "HERE=%~dp0"
echo.
echo  正在解除本文件夹（含子目录）内所有文件的锁定...
echo  目录：%HERE%
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$n=0; Get-ChildItem -LiteralPath '%HERE%' -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object { if (Get-Item -LiteralPath $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue) { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue; $n++ } }; Write-Host ('  已解锁文件数：' + $n)"
echo.
echo  完成。现在可以正常双击“启动_可运行作品.cmd”运行本平台。
echo.
pause
exit /b 0
