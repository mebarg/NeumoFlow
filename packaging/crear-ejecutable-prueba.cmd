@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1" -AppOnly
if errorlevel 1 (
  echo.
  echo No se pudo generar el ejecutable. Envia el error que aparece arriba.
) else (
  echo.
  echo Abre dist\NeumoFlow\NeumoFlow.exe para probarlo.
  echo Conserva todos los archivos de esa carpeta junto al EXE.
)
pause
