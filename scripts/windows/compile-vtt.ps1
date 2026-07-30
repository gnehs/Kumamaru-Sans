[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BaselineFont,

    [Parameter(Mandatory = $true)]
    [string]$SourceFont,

    [Parameter(Mandatory = $true)]
    [string]$OutputFont,

    [string]$VttShellPath = "",
    [string]$PythonCommand = "python",
    [string]$PilotText = "日田國圓"
)

$ErrorActionPreference = "Stop"

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "VTTShell requires Windows."
}

$BaselineFont = (Resolve-Path -LiteralPath $BaselineFont).Path
$SourceFont = (Resolve-Path -LiteralPath $SourceFont).Path
$OutputFont = [System.IO.Path]::GetFullPath($OutputFont)
if ($BaselineFont -eq $SourceFont -or $BaselineFont -eq $OutputFont -or $SourceFont -eq $OutputFont) {
    throw "Baseline, editable source, and output paths must be different."
}
if (Test-Path -LiteralPath $OutputFont) {
    throw "Refusing to overwrite existing output: $OutputFont"
}

if (-not $VttShellPath) {
    $VttShellPath = Join-Path $env:ProgramFiles "Microsoft Visual TrueType\vttshell.exe"
}
if (-not (Test-Path -LiteralPath $VttShellPath)) {
    throw "Missing vttshell.exe: $VttShellPath"
}

$OutputDirectory = Split-Path -Parent $OutputFont
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputStem = [System.IO.Path]::GetFileNameWithoutExtension($OutputFont)
$CompiledWithSource = Join-Path $OutputDirectory "$OutputStem.with-source.ttf"
$SourceReport = Join-Path $OutputDirectory "$OutputStem.source-report.json"
$CompiledReport = Join-Path $OutputDirectory "$OutputStem.compiled-report.json"
$FinalPaths = @($CompiledWithSource, $SourceReport, $CompiledReport, $OutputFont)
$ExistingPaths = @($FinalPaths | Where-Object { Test-Path -LiteralPath $_ })
if ($ExistingPaths.Count -gt 0) {
    throw "Refusing to overwrite existing VTT outputs: $($ExistingPaths -join ', ')"
}

$Nonce = [System.Guid]::NewGuid().ToString("N")
$TemporaryCompiled = Join-Path $OutputDirectory ".$OutputStem.$Nonce.with-source.ttf"
$TemporaryOutput = Join-Path $OutputDirectory ".$OutputStem.$Nonce.compiled.ttf"
$TemporarySourceReport = Join-Path $OutputDirectory ".$OutputStem.$Nonce.source-report.json"
$TemporaryCompiledReport = Join-Path $OutputDirectory ".$OutputStem.$Nonce.compiled-report.json"
$TemporaryPaths = @(
    $TemporaryCompiled,
    $TemporaryOutput,
    $TemporarySourceReport,
    $TemporaryCompiledReport
)
$PublishedPaths = [System.Collections.Generic.List[string]]::new()

try {
    & $PythonCommand -m kumamaru.vtt_contract validate `
        --baseline $BaselineFont `
        --font $SourceFont `
        --stage source `
        --pilot-text $PilotText `
        --report $TemporarySourceReport
    if ($LASTEXITCODE -ne 0) {
        throw "Editable VTT source contract failed."
    }

    & $VttShellPath "-a" $SourceFont $TemporaryCompiled
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $TemporaryCompiled)) {
        throw "VTTShell full compilation failed with exit code $LASTEXITCODE."
    }

    & $VttShellPath "-s" $TemporaryCompiled $TemporaryOutput
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $TemporaryOutput)) {
        throw "VTTShell source stripping failed with exit code $LASTEXITCODE."
    }

    & $PythonCommand -m kumamaru.vtt_contract validate `
        --baseline $BaselineFont `
        --font $TemporaryOutput `
        --stage compiled `
        --pilot-text $PilotText `
        --report $TemporaryCompiledReport
    if ($LASTEXITCODE -ne 0) {
        throw "Compiled VTT delivery contract failed."
    }

    $Publications = @(
        [pscustomobject]@{ Temporary = $TemporaryCompiled; Final = $CompiledWithSource }
        [pscustomobject]@{ Temporary = $TemporarySourceReport; Final = $SourceReport }
        [pscustomobject]@{ Temporary = $TemporaryCompiledReport; Final = $CompiledReport }
        [pscustomobject]@{ Temporary = $TemporaryOutput; Final = $OutputFont }
    )
    foreach ($Publication in $Publications) {
        Move-Item -LiteralPath $Publication.Temporary -Destination $Publication.Final
        $PublishedPaths.Add($Publication.Final)
    }
}
catch {
    foreach ($PublishedPath in $PublishedPaths) {
        Remove-Item -LiteralPath $PublishedPath -Force -ErrorAction SilentlyContinue
    }
    throw
}
finally {
    foreach ($TemporaryPath in $TemporaryPaths) {
        Remove-Item -LiteralPath $TemporaryPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Compiled VTT font: $OutputFont"
Write-Host "Source report: $SourceReport"
Write-Host "Compiled report: $CompiledReport"
