$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if ($env:OS -ne "Windows_NT") { throw "Ejecutar dentro de Windows 10 x64." }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Fallo $Exe (codigo $LASTEXITCODE)." }
}

Push-Location $repo
try {
    New-Item -ItemType Directory -Force "build" | Out-Null
    Invoke-Checked "py" @("-3.12", "-c", "import struct; assert struct.calcsize('P') == 8, 'Se requiere Python x64'")
    if (-not (Test-Path ".venv-win\Scripts\python.exe")) {
        Invoke-Checked "py" @("-3.12", "-m", "venv", ".venv-win")
    }
    $python = Join-Path $repo ".venv-win\Scripts\python.exe"
    Invoke-Checked $python @("-c", "import sys,struct; assert struct.calcsize('P') == 8; assert sys.version_info[:2] == (3,12)")
    Invoke-Checked $python @("-m", "pip", "install", "--only-binary=libusb-package", "-r", "requirements.txt", "-c", "packaging\constraints-windows.txt")
    Invoke-Checked $python @("-m", "app.main", "--self-test", "build\windows-app-self-test.json")
    Write-Host "Abriendo la aplicacion. Esta prueba no genera el instalador final."
    Invoke-Checked $python @("-m", "app.main")
} finally {
    Pop-Location
}
