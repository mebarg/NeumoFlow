param([string]$InnoCompiler = "", [switch]$AppOnly)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if ($env:OS -ne "Windows_NT") { throw "Este script debe ejecutarse en Windows x64." }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Falló $Exe (código $LASTEXITCODE)." }
}

Push-Location $repo
try {
    Invoke-Checked "py" @("-3.12", "-c", "import sys,struct; assert struct.calcsize('P') == 8, 'Se requiere Python x64'; assert sys.version_info[:2] == (3,12)")
    if (-not (Test-Path ".venv-win\Scripts\python.exe")) {
        Invoke-Checked "py" @("-3.12", "-m", "venv", ".venv-win")
    }
    $python = Join-Path $repo ".venv-win\Scripts\python.exe"
    Invoke-Checked $python @("-c", "import sys,struct; assert struct.calcsize('P') == 8; assert sys.version_info[:2] == (3,12), 'La carpeta .venv-win debe usar Python 3.12 x64'")
    if (-not $AppOnly) {
        Invoke-Checked $python @("packaging\check_usb_bundle.py")
        Invoke-Checked "powershell.exe" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "packaging\setup-usb-windows.ps1", "-ValidateOnly")
    }
    Invoke-Checked $python @("-m", "pip", "install", "--only-binary=libusb-package", "-r", "requirements.txt", "-r", "requirements-build.txt", "-c", "packaging\constraints-windows.txt")
    Invoke-Checked $python @("-m", "unittest", "discover", "-s", "tests", "-q")
    Invoke-Checked $python @("-m", "PyInstaller", "--clean", "--noconfirm", "packaging\espirometro.spec")

    $report = Join-Path $repo "build\windows-self-test.json"
    if (Test-Path $report) { Remove-Item $report }
    $exe = Join-Path $repo "dist\Espirometro\Espirometro.exe"
    $process = Start-Process -FilePath $exe -ArgumentList @("--self-test", "`"$report`"") -Wait -PassThru
    if ($process.ExitCode -ne 0 -or -not (Test-Path $report)) {
        throw "El ejecutable no pasó la comprobación de arranque. Revisar $report"
    }
    $check = Get-Content $report -Raw | ConvertFrom-Json
    if (-not $check.ok) { throw "Falló la comprobación de recursos: $($check.error)" }
    $packages = & $python -m pip freeze --all
    if ($LASTEXITCODE -ne 0) { throw "No se pudo registrar la versión de las dependencias." }
    $packages | Set-Content -Encoding UTF8 "build\windows-packages.txt"

    if ($AppOnly) {
        Write-Host "Ejecutable de prueba generado: $exe"
        Write-Host "Conservar toda la carpeta dist\Espirometro junto al EXE."
        Write-Host "Esta compilacion no instala el controlador USB."
        return
    }

    if (-not $InnoCompiler) {
        $found = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
        if ($found) { $InnoCompiler = $found.Source }
        else { $InnoCompiler = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe" }
    }
    if (-not (Test-Path $InnoCompiler)) { throw "Instalá Inno Setup 6 o pasá -InnoCompiler con la ruta a ISCC.exe." }
    Invoke-Checked $InnoCompiler @("packaging\espirometro.iss")
    $installer = Join-Path $repo "dist-installer\EspirometroSetup-1.0.0.exe"
    Get-FileHash -Algorithm SHA256 $installer | Format-List
    Write-Host "Instalador generado: $installer"
} finally {
    Pop-Location
}
