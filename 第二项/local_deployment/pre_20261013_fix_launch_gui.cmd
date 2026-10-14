@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_gui.ps1"
exit /b %ERRORLEVEL%
