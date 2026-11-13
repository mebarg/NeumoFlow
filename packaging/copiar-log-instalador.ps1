$ErrorActionPreference = "Stop"
$source = Join-Path $env:ProgramData "Espirometro\USB\setup-usb.log"
$target = Join-Path (Split-Path -Parent $PSScriptRoot) "build\windows-usb-setup.log"
if (-not (Test-Path $source)) {
    throw "No existe $source. Envia este mensaje para revisar el arranque del asistente USB."
}
New-Item -ItemType Directory -Force (Split-Path -Parent $target) | Out-Null
Copy-Item $source $target -Force
Write-Host "Registro copiado a la carpeta compartida."
