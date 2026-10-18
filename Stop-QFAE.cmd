@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop-QFAE.ps1"
if errorlevel 1 (
  echo.
  echo Q-FAE shutdown encountered an error. Review the message above.
  pause
)
endlocal

