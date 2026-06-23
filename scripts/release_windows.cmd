@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release_windows.ps1" %*
exit /b %ERRORLEVEL%
