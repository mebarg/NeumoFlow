@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0copiar-log-instalador.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo copiar el registro. Envia el mensaje que aparece arriba.
)
pause
