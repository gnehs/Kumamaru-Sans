[CmdletBinding()]
param(
    [string]$InstallerPath = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$VttVersion = "6.35"
$VttUri = "https://download.microsoft.com/download/1/6/3/1633189b-8cf4-4787-b2e9-af3d6595e0f2/Microsoft%20Visual%20TrueType-64.msi"
$VttSha256 = "5242c74562757482375e8b19035acf5df5fe37d92682bc56b49fa18c5332117a"

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Microsoft Visual TrueType $VttVersion requires Windows."
}
$OperatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem
if ($OperatingSystem.Caption -notmatch "Windows 10|Windows 11") {
    throw "VTT 6.35 is supported only on Windows 10/11; found $($OperatingSystem.Caption)."
}
if ($OperatingSystem.OSArchitecture -notmatch "64-bit") {
    throw "The pinned VTT installer requires 64-bit Windows; found $($OperatingSystem.OSArchitecture)."
}
if (-not $InstallerPath) {
    $InstallerPath = Join-Path ([System.IO.Path]::GetTempPath()) "Microsoft-Visual-TrueType-64.msi"
}
if (-not $LogPath) {
    $LogPath = Join-Path ([System.IO.Path]::GetTempPath()) "vtt-install.log"
}

Invoke-WebRequest -Uri $VttUri -OutFile $InstallerPath
$ActualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath).Hash.ToLowerInvariant()
if ($ActualSha256 -ne $VttSha256) {
    throw "VTT installer SHA-256 mismatch: expected $VttSha256, got $ActualSha256"
}

$Signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
if ($Signature.Status -ne "Valid") {
    throw "VTT installer signature is not valid: $($Signature.Status)"
}
if (-not $Signature.SignerCertificate.Subject.Contains("Microsoft Corporation")) {
    throw "VTT installer signer is not Microsoft Corporation: $($Signature.SignerCertificate.Subject)"
}

$Arguments = @(
    "/i",
    "`"$InstallerPath`"",
    "/qn",
    "/norestart",
    "/L*v",
    "`"$LogPath`""
)
$Installer = Start-Process -FilePath "msiexec.exe" -ArgumentList $Arguments -Wait -PassThru
if ($Installer.ExitCode -notin @(0, 3010)) {
    throw "VTT installation failed with exit code $($Installer.ExitCode); see $LogPath"
}

$Candidates = @(
    (Join-Path $env:ProgramFiles "Microsoft Visual TrueType\vttshell.exe"),
    (Join-Path $env:ProgramFiles "Microsoft Visual TrueType\VttShell.exe")
)
$VttShell = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $VttShell) {
    $VttShell = Get-ChildItem -Path $env:ProgramFiles -Filter "vttshell.exe" -File -Recurse |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $VttShell) {
    throw "VTT installed, but vttshell.exe was not found below Program Files."
}
$InstalledVersion = (Get-Item -LiteralPath $VttShell).VersionInfo.ProductVersion
if ($InstalledVersion -notmatch "^6\.(3\.5|35)(\.|$)") {
    throw "Unexpected VTTShell product version: $InstalledVersion"
}

Write-Host "Installed Microsoft Visual TrueType $InstalledVersion"
Write-Host "VTTShell: $VttShell"
if ($env:GITHUB_PATH) {
    Split-Path -Parent $VttShell | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
}
if ($env:GITHUB_OUTPUT) {
    "path=$VttShell" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
    "version=$InstalledVersion" | Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
    "installer_sha256=$VttSha256" |
        Out-File -FilePath $env:GITHUB_OUTPUT -Encoding utf8 -Append
}
