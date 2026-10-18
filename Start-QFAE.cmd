@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-QFAE.ps1"
if errorlevel 1 (
  echo.
  echo Q-FAE startup failed. Review the message above.
  pause
)
endlocal

