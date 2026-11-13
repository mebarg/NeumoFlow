@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0probar-app-windows.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo completar la prueba. Envia el error que aparece arriba.
)
pause
