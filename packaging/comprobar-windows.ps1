# Read-only environment check. Does not install tools, open USB or change drivers.
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Ejecutar esta comprobacion dentro de Windows." }
$report = [ordered]@{
    checked_at = (Get-Date).ToString("o")
    windows_version = [Environment]::OSVersion.Version.ToString()
    windows_64bit = [Environment]::Is64BitOperatingSystem
    python312_x64 = $false
    python_version = $null
    inno_compiler = $null
    msbuild = $null
    windows_kits = @()
    usb_helper_present = (Test-Path (Join-Path $PSScriptRoot "windows-usb\wdi-simple.exe"))
}
$py = Get-Command "py.exe" -ErrorAction SilentlyContinue
if ($py) {
    $previousAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $pythonResult = & $py.Source -3.12 -c "import json,sys,struct; print(json.dumps({'version':sys.version.split()[0],'bits':struct.calcsize('P')*8}))" 2>$null
        $pythonExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousAction }
    if ($pythonExit -eq 0) {
        $details = $pythonResult | ConvertFrom-Json
        $report.python_version = $details.version
        $report.python312_x64 = ($details.bits -eq 64)
    }
}
$programFilesX86 = ${env:ProgramFiles(x86)}
if (-not $programFilesX86) { $programFilesX86 = $env:ProgramFiles }
$inno = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($inno) { $report.inno_compiler = $inno.Source }
else {
    $innoPath = Join-Path $programFilesX86 "Inno Setup 6\ISCC.exe"
    if (Test-Path $innoPath) { $report.inno_compiler = $innoPath }
}
$msbuild = Get-Command "MSBuild.exe" -ErrorAction SilentlyContinue
if ($msbuild) { $report.msbuild = $msbuild.Source }
else {
    $vswhere = Join-Path $programFilesX86 "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $located = & $vswhere -latest -products '*' -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe'
        if ($located) { $report.msbuild = @($located)[0] }
    }
}
$kits = Join-Path $programFilesX86 "Windows Kits"
if (Test-Path $kits) {
    $report.windows_kits = @(Get-ChildItem $kits -Directory | ForEach-Object { $_.Name })
}
$destination = Join-Path $PSScriptRoot "windows-status.json"
$report | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $destination
Write-Host "Comprobacion completada sin modificar Windows ni el espirometro."
Write-Host "Resultado: $destination"
