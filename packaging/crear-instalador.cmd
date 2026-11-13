@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo generar el instalador. Revisa el error que aparece arriba.
) else (
  echo.
  echo Instalador generado en la carpeta dist-installer.
)
pause
