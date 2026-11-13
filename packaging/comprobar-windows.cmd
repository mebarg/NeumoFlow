@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0comprobar-windows.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo guardar la comprobacion. Copia el mensaje de error que aparece arriba.
) else (
  echo.
  echo Comprobacion guardada. Volve a la conversacion e indica que ya termino.
)
pause
