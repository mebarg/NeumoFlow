param([string]$InnoCompiler = "", [switch]$AppOnly, [string]$Version = "", [string]$PythonExe = "")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if ($env:OS -ne "Windows_NT") { throw "Este script debe ejecutarse en Windows x64." }
$savedEnvironment = @{}
foreach ($name in @("LOCALAPPDATA", "APPDATA", "XDG_DATA_HOME", "QT_QPA_PLATFORM")) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Fallo $Exe (codigo $LASTEXITCODE)." }
}

Push-Location $repo
try {
    $versionLine = Select-String -Path "packaging\espirometro.iss" -Pattern '^#define MyAppVersion "([0-9.]+)"$'
    if (-not $versionLine) { throw "No se pudo leer la version del instalador." }
    $appVersion = $versionLine.Matches[0].Groups[1].Value
    if ($Version) { $appVersion = $Version }
    if ($appVersion -cnotmatch "^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$") { throw "Version invalida: usar X.Y.Z." }
    foreach ($part in $appVersion.Split(".")) {
        if ($part.Length -gt 5 -or [int]$part -gt 65535) { throw "Cada parte de la version debe ser menor que 65536." }
    }
    $installer = Join-Path $repo "dist-installer\NeumoFlowSetup-$appVersion.exe"
    if (-not $AppOnly) {
        if (Test-Path $installer) { throw "Ya existe $installer. Conserva esa entrega en otra carpeta antes de recompilar." }
        if (-not $InnoCompiler) {
            $found = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
            if ($found) { $InnoCompiler = $found.Source }
            else {
                $candidates = @(
                    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
                    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
                    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
                )
                foreach ($candidate in $candidates) {
                    if (Test-Path $candidate) { $InnoCompiler = $candidate; break }
                }
            }
        }
        if (-not $InnoCompiler -or -not (Test-Path $InnoCompiler)) {
            throw "Instala Inno Setup 6 o pasa -InnoCompiler con la ruta a ISCC.exe."
        }
    }
    New-Item -ItemType Directory -Force "build" | Out-Null
    $bootstrap = "py"
    $bootstrapArgs = @("-3.12")
    if ($PythonExe) { $bootstrap = $PythonExe; $bootstrapArgs = @() }
    Invoke-Checked $bootstrap ($bootstrapArgs + @("-c", "import sys,struct; assert struct.calcsize('P') == 8, 'Se requiere Python x64'; assert sys.version_info[:2] == (3,12)"))
    if (-not (Test-Path ".venv-win\Scripts\python.exe")) {
        Invoke-Checked $bootstrap ($bootstrapArgs + @("-m", "venv", ".venv-win"))
    }
    $python = Join-Path $repo ".venv-win\Scripts\python.exe"
    Invoke-Checked $python @("-c", "import sys,struct; assert struct.calcsize('P') == 8; assert sys.version_info[:2] == (3,12), 'La carpeta .venv-win debe usar Python 3.12 x64'")
    if (-not $AppOnly) {
        Invoke-Checked $python @("packaging\check_usb_bundle.py")
        Invoke-Checked "powershell.exe" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "packaging\setup-usb-windows.ps1", "-ValidateOnly")
    }
    Invoke-Checked $python @("-m", "pip", "install", "--only-binary=libusb-package", "-r", "requirements.txt", "-r", "requirements-build.txt", "-c", "packaging\constraints-windows.txt")
    # Isolate the test runner and frozen check from the operator's real data.
    $testData = Join-Path ([IO.Path]::GetTempPath()) ("NeumoFlow-build-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $testData | Out-Null
    $env:LOCALAPPDATA = $testData
    $env:APPDATA = $testData
    $env:XDG_DATA_HOME = $testData
    # The generic offscreen plugin has no Windows system-font backend.
    # Use the same native plugin as the installed application.
    $env:QT_QPA_PLATFORM = "windows"
    $sourceReport = Join-Path $repo "build\windows-source-self-test.json"
    if (Test-Path $sourceReport) { Remove-Item $sourceReport }
    & $python -m app.main --self-test $sourceReport
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path $sourceReport) { Get-Content $sourceReport -Raw | Write-Host }
        throw "Fallo la comprobacion inicial de Qt, fuentes o recursos. Revisar $sourceReport"
    }
    Invoke-Checked $python @("-m", "unittest", "discover", "-s", "tests", "-q")
    Invoke-Checked $python @("-m", "PyInstaller", "--clean", "--noconfirm", "packaging\espirometro.spec")

    $report = Join-Path $repo "build\windows-self-test.json"
    if (Test-Path $report) { Remove-Item $report }
    $exe = Join-Path $repo "dist\NeumoFlow\NeumoFlow.exe"
    $process = Start-Process -FilePath $exe -ArgumentList @("--self-test", "`"$report`"") -Wait -PassThru
    if ($process.ExitCode -ne 0 -or -not (Test-Path $report)) {
        throw "El ejecutable no paso la comprobacion de arranque. Revisar $report"
    }
    $check = Get-Content $report -Raw | ConvertFrom-Json
    if (-not $check.ok) { throw "Fallo la comprobacion de recursos: $($check.error)" }
    $packages = & $python -m pip freeze --all
    if ($LASTEXITCODE -ne 0) { throw "No se pudo registrar la version de las dependencias." }
    $packages | Set-Content -Encoding UTF8 "build\windows-packages.txt"

    if ($AppOnly) {
        Write-Host "Ejecutable de prueba generado: $exe"
        Write-Host "Conservar toda la carpeta dist\NeumoFlow junto al EXE."
        Write-Host "Esta compilacion no instala el controlador USB."
        return
    }

    Invoke-Checked $InnoCompiler @("/DMyAppVersion=$appVersion", "packaging\espirometro.iss")
    if (-not (Test-Path $installer)) { throw "El compilador termino sin generar $installer." }
    $hash = Get-FileHash -Algorithm SHA256 $installer
    ($hash.Hash.ToLowerInvariant() + "  " + (Split-Path -Leaf $installer)) | Set-Content -Encoding ASCII "$installer.sha256"
    $hash | Format-List
    Write-Host "Instalador generado: $installer"
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
    }
    Pop-Location
}
