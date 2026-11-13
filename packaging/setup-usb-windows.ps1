param(
    [string]$Package = (Join-Path $PSScriptRoot "windows-usb\package"),
    [switch]$ValidateOnly
)
$ErrorActionPreference = "Stop"
if (-not $ValidateOnly) {
    $logDir = Join-Path $env:ProgramData "Espirometro\USB"
    New-Item -ItemType Directory -Force $logDir | Out-Null
    Start-Transcript -Path (Join-Path $logDir "setup-usb.log") -Append | Out-Null
}
$expectedThumbprint = "AE87D0D43947DE135B9C33F87D00CE9E9ED25D2B"
$manifest = Get-Content (Join-Path $Package "manifest.json") -Raw | ConvertFrom-Json
if ($manifest.device_id -ne 'USB\VID_0EE5&PID_0103' -or
    $manifest.certificate_thumbprint -ne $expectedThumbprint) { throw "Unexpected USB package" }
$required = @('Medical_Graphics_CPFS_USB.inf', 'Medical_Graphics_CPFS_USB.cat',
    'amd64/WdfCoInstaller01011.dll', 'amd64/winusbcoinstaller2.dll',
    'x86/WdfCoInstaller01011.dll', 'x86/winusbcoinstaller2.dll', 'signer.cer')
if (@($manifest.sha256.PSObject.Properties).Count -ne $required.Count) { throw "Unexpected USB files" }
foreach ($name in $required) {
    $path = Join-Path $Package $name
    if ((Get-FileHash $path -Algorithm SHA256).Hash -ne $manifest.sha256.$name) {
        throw "USB hash mismatch: $name"
    }
}
$certificate = New-Object Security.Cryptography.X509Certificates.X509Certificate2 (Join-Path $Package "signer.cer")
if ($certificate.Thumbprint -ne $expectedThumbprint -or $certificate.HasPrivateKey -or
    (Get-Date) -lt $certificate.NotBefore -or (Get-Date) -ge $certificate.NotAfter) {
    throw "USB certificate invalid or expired"
}
$catalog = Join-Path $Package "Medical_Graphics_CPFS_USB.cat"
$signature = Get-AuthenticodeSignature $catalog
if ($signature.SignerCertificate.Thumbprint -ne $expectedThumbprint) { throw "Unexpected catalog signer" }
if ($ValidateOnly) {
    if ($signature.Status -ne 'Valid') { throw "Catalog signature: $($signature.Status)" }
    Write-Host "Windows USB package signature checked."
    exit 0
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal $identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "USB setup requires administrator"
}
# Same trust stores as libwdi. Only this pinned public certificate is imported.
# No private key, test-signing mode, generic driver or filter is installed.
foreach ($store in @('Root', 'TrustedPublisher')) {
    & "$env:SystemRoot\System32\certutil.exe" -addstore -f $store (Join-Path $Package "signer.cer")
    if ($LASTEXITCODE -ne 0) { throw "Could not register USB certificate ($store)" }
}
$signature = Get-AuthenticodeSignature $catalog
if ($signature.Status -ne 'Valid') { throw "USB catalog signature: $($signature.Status)" }
& "$env:SystemRoot\System32\pnputil.exe" /add-driver (Join-Path $Package 'Medical_Graphics_CPFS_USB.inf') /install
$installResult = $LASTEXITCODE
if ($installResult -notin @(0, 259, 3010)) { throw "USB install failed: $installResult" }
if ($installResult -eq 3010) { exit 3010 }
# 259 can mean no matching devices OR an existing equal/better driver. Do not
# treat it as success unless this exact signed package is already registered.
if ($installResult -eq 259) {
    $expectedInfHash = $manifest.sha256.'Medical_Graphics_CPFS_USB.inf'
    $registered = $false
    foreach ($inf in @(Get-ChildItem (Join-Path $env:SystemRoot 'INF') -Filter 'oem*.inf' -File)) {
        if ((Get-FileHash $inf.FullName -Algorithm SHA256).Hash -eq $expectedInfHash) {
            $registered = $true
            break
        }
    }
    if (-not $registered) { throw "PnPUtil returned 259 but the CPFS/D package is not registered" }
    Write-Host "PnPUtil returned 259; the exact CPFS/D package is registered. Checking connected devices."
}
# PnPUtil does not override higher ranked incompatible drivers. Detect that.
$devices = @(Get-CimInstance Win32_PnPEntity | Where-Object {
    $_.DeviceID -match '^USB\\VID_0EE5&PID_0103(?:\\|&)' -and $_.Present -eq $true
})
foreach ($device in $devices) {
    if ($device.Service -ne 'WinUSB' -or $device.ConfigManagerErrorCode -ne 0) {
        throw "The connected CPFS/D does not have an active WinUSB driver"
    }
}
Write-Host "CPFS/D USB package installed."
exit 0
