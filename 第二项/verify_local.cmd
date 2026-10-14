@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_local.ps1"
set "verify_exit=%ERRORLEVEL%"
echo.
if "%verify_exit%"=="0" (echo Local deployment verification passed.) else (echo Verification failed. Read the validation reports.)
pause
exit /b %verify_exit%
