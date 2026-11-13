@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0recoger-controlador-windows.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo completar la copia. Envia el error que aparece arriba.
)
pause
