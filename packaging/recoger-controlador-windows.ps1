$ErrorActionPreference = "Stop"
$output = Join-Path $PSScriptRoot "windows-usb\exported"
New-Item -ItemType Directory -Force $output | Out-Null
$devices = @(Get-CimInstance Win32_PnPSignedDriver | Where-Object {
    $_.DeviceID -match '^USB\\VID_0EE5&PID_0103(?:\\|&)'
})
if ($devices.Count -eq 0) {
    throw "No se encontro el CPFS/D. Conectalo a esta maquina virtual y repeti."
}
$results = @()
foreach ($device in $devices) {
    $inf = $device.InfName
    if ($inf -notmatch '^oem[0-9]+\.inf$') {
        throw "El controlador detectado no tiene un paquete OEM exportable: $inf"
    }
    $destination = Join-Path $output $inf
    New-Item -ItemType Directory -Force $destination | Out-Null
    $log = & "$env:SystemRoot\System32\pnputil.exe" /export-driver $inf $destination 2>&1
    $code = $LASTEXITCODE
    $log | Set-Content -Encoding UTF8 (Join-Path $destination "export-log.txt")
    $catalogs = @(Get-ChildItem $destination -Recurse -Filter *.cat | ForEach-Object {
        $signature = Get-AuthenticodeSignature $_.FullName
        if ($signature.SignerCertificate) {
            # Public certificate only: never export a private key.
            $certificatePath = Join-Path $destination "signer.cer"
            [IO.File]::WriteAllBytes($certificatePath, $signature.SignerCertificate.Export(
                [Security.Cryptography.X509Certificates.X509ContentType]::Cert))
        }
        [ordered]@{
            file = $_.FullName
            status = [string]$signature.Status
            signer = $signature.SignerCertificate.Subject
            thumbprint = $signature.SignerCertificate.Thumbprint
        }
    })
    $originalPackages = @()
    $exportedInfs = @(Get-ChildItem $destination -Recurse -Filter *.inf)
    $roots = @(
        (Join-Path $env:SystemDrive "usb_driver"),
        (Join-Path $env:USERPROFILE "usb_driver"),
        (Join-Path $env:USERPROFILE "Downloads\usb_driver"),
        (Join-Path (Split-Path -Parent $PSScriptRoot) "usb_driver")
    ) | Select-Object -Unique
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($candidate in @(Get-ChildItem $root -Recurse -Filter *.inf -ErrorAction SilentlyContinue)) {
            foreach ($exportedInf in $exportedInfs) {
                if ((Get-FileHash $candidate.FullName -Algorithm SHA256).Hash -ne
                    (Get-FileHash $exportedInf.FullName -Algorithm SHA256).Hash) { continue }
                $copy = Join-Path $output ("original-" + $originalPackages.Count)
                New-Item -ItemType Directory -Force $copy | Out-Null
                Copy-Item (Join-Path $candidate.DirectoryName "*") $copy -Recurse -Force
                $originalPackages += $candidate.DirectoryName
            }
        }
    }
    $results += [ordered]@{
        device = $device.DeviceName
        hardware_id = $device.DeviceID
        provider = $device.DriverProviderName
        version = $device.DriverVersion
        inf = $inf
        export_exit_code = $code
        catalogs = $catalogs
        original_packages = $originalPackages
        files = @(Get-ChildItem $output -Recurse -File | ForEach-Object { $_.FullName })
    }
}
ConvertTo-Json -InputObject $results -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $output "driver-report.json")
Write-Host "Resultado guardado en packaging\windows-usb\exported."
if (@($results | Where-Object { $_.export_exit_code -ne 0 }).Count -gt 0) {
    throw "Windows no pudo exportar el paquete. El motivo quedo guardado en export-log.txt."
}
Write-Host "Controlador copiado para revision. No se modifico su instalacion."
