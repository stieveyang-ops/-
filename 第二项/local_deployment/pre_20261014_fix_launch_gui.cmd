@echo off
rem Encoding guard (mirrors launch_gui.ps1): keep Python in UTF-8 mode so the
rem AiZynthFinder child process can read its config file when the package is
rem installed under a non-ASCII path on a cp936/GBK Windows locale.
setlocal
set "PYTHONUTF8=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_gui.ps1"
exit /b %ERRORLEVEL%
