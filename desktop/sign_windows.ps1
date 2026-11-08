# Authenticode-sign a release PE, RFC 3161 timestamp it, and verify what landed.
#
# This is a RELEASE STAGE, not a build step: the compile job never sets any of the
# CIXI_SIGN_* values and never needs a certificate. Run it only after UPX (packing
# rewrites the PE and destroys a signature) and before the installer wraps the bytes;
# run it again on the Setup.exe Inno produced.
#
#   powershell -ExecutionPolicy Bypass -File desktop\sign_windows.ps1 -Target dist\CaiXiHui\CaiXiHui.exe
#   powershell -ExecutionPolicy Bypass -File desktop\sign_windows.ps1 -Target dist\CaiXiHui-Setup.exe
#
# Credential modes (CIXI_SIGN_MODE, inferred when a mode-specific variable is set):
#   pfx     CIXI_SIGN_PFX + CIXI_SIGN_PASSWORD    local / code-signing certificate
#   subject CIXI_SIGN_SUBJECT                     certificate already in the user store
#   azure   CIXI_SIGN_DLIB + CIXI_SIGN_DMDF        Azure Artifact Signing dlib and metadata
# CIXI_SIGNTOOL overrides signtool.exe discovery; CIXI_SIGN_TIMESTAMP overrides the
# RFC 3161 server. -AllowUntrustedRoot is for a local self-signed smoke test ONLY:
# it prints a loud warning and still requires a real signature and a timestamp.
#
# No secret is ever printed. A missing tool, credential, signature or timestamp is
# refused BY NAME with a non-zero exit; the release chain must not "pass unsigned".

param(
    [Parameter(Mandatory = $true)] [string[]]$Target,
    [string]$TimestampUrl = '',
    [switch]$AllowUntrustedRoot
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Get-EnvOr([string]$Name, [string]$Fallback) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { return $value }
    return $Fallback
}

function Find-SignTool {
    $candidates = @()
    if ($env:CIXI_SIGNTOOL) { $candidates += $env:CIXI_SIGNTOOL }
    $roots = @()
    if (${env:ProgramFiles(x86)}) { $roots += (Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin') }
    if ($env:ProgramFiles) { $roots += (Join-Path $env:ProgramFiles 'Windows Kits\10\bin') }
    foreach ($kits in $roots) {
        if (-not (Test-Path -LiteralPath $kits)) { continue }
        $found = Get-ChildItem -LiteralPath $kits -Filter 'signtool.exe' -Recurse -Depth 2 -ErrorAction SilentlyContinue
        $candidates += ($found | ForEach-Object { $_.FullName })
    }
    $onPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += $onPath.Source }
    $found = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $found) {
        throw 'signtool.exe not found: set CIXI_SIGNTOOL, install the Windows SDK, or put it on PATH'
    }
    return $found
}

function Get-SignArguments([string]$Mode, [string]$Timestamp) {
    $arguments = @('sign', '/fd', 'SHA256', '/tr', $Timestamp, '/td', 'SHA256')
    switch ($Mode) {
        'pfx' {
            $pfx = [Environment]::GetEnvironmentVariable('CIXI_SIGN_PFX')
            $password = [Environment]::GetEnvironmentVariable('CIXI_SIGN_PASSWORD')
            if (-not $pfx) { throw 'pfx mode needs CIXI_SIGN_PFX (path to the .pfx)' }
            if (-not (Test-Path -LiteralPath $pfx)) { throw "pfx file does not exist: $pfx" }
            if ($null -eq $password) { throw 'pfx mode needs CIXI_SIGN_PASSWORD (use an empty value for a passwordless pfx)' }
            # signtool only accepts /p on the command line; do not echo $arguments anywhere.
            $arguments += @('/f', $pfx, '/p', $password)
        }
        'subject' {
            $subject = [Environment]::GetEnvironmentVariable('CIXI_SIGN_SUBJECT')
            if (-not $subject) { throw 'subject mode needs CIXI_SIGN_SUBJECT' }
            $arguments += @('/n', $subject)
        }
        'azure' {
            $dlib = [Environment]::GetEnvironmentVariable('CIXI_SIGN_DLIB')
            $dmdf = [Environment]::GetEnvironmentVariable('CIXI_SIGN_DMDF')
            if (-not $dlib -or -not (Test-Path -LiteralPath $dlib)) {
                throw 'azure mode needs CIXI_SIGN_DLIB pointing at Azure.CodeSigning.Dlib.dll'
            }
            if (-not $dmdf -or -not (Test-Path -LiteralPath $dmdf)) {
                throw 'azure mode needs CIXI_SIGN_DMDF pointing at the signing metadata JSON'
            }
            $arguments += @('/dlib', $dlib, '/dmdf', $dmdf)
        }
        default {
            throw "unknown CIXI_SIGN_MODE '$Mode': expected pfx, subject or azure"
        }
    }
    return $arguments
}

function Assert-Pe([string]$File) {
    $bytes = [System.IO.File]::ReadAllBytes($File)
    if ($bytes.Length -lt 2 -or (($bytes[0..1] -join '.') -ne '77.90')) {
        throw "$File is not a PE (expected the MZ header); refusing to sign anything else"
    }
}

function Assert-Signature([string]$File, [switch]$AllowUntrusted) {
    $signature = Get-AuthenticodeSignature -LiteralPath $File
    if ($signature.Status -eq 'NotSigned' -or -not $signature.SignerCertificate) {
        throw "$File has no Authenticode signature after signtool ran"
    }
    if ($signature.Status -ne 'Valid') {
        if ($AllowUntrusted -and $signature.Status -eq 'UnknownError') {
            Write-Warning "UNTRUSTED ROOT accepted for a local test only: $File -- do not publish these bytes"
        } else {
            throw "$File signature status is $($signature.Status): $($signature.StatusMessage)"
        }
    }
    if (-not $signature.TimeStamperCertificate) {
        throw "$File has no RFC 3161 timestamp: the certificate would expire with the signature"
    }
    Write-Host ("Signed: {0} | signer: {1} | timestamp: {2}" -f $File,
        $signature.SignerCertificate.Subject, $signature.TimeStamperCertificate.Subject)
}

if (-not $Target -or $Target.Count -eq 0) {
    throw 'no -Target files were given'
}
$timestamp = Get-EnvOr 'CIXI_SIGN_TIMESTAMP' 'http://timestamp.digicert.com'
if ($TimestampUrl) { $timestamp = $TimestampUrl }

$mode = Get-EnvOr 'CIXI_SIGN_MODE' ''
if (-not $mode) {
    if ([Environment]::GetEnvironmentVariable('CIXI_SIGN_DLIB')) { $mode = 'azure' }
    elseif ([Environment]::GetEnvironmentVariable('CIXI_SIGN_PFX')) { $mode = 'pfx' }
    elseif ([Environment]::GetEnvironmentVariable('CIXI_SIGN_SUBJECT')) { $mode = 'subject' }
    else { throw 'no signing credentials: set CIXI_SIGN_MODE (pfx|subject|azure) and its CIXI_SIGN_* values' }
}
$signtool = Find-SignTool
$common = Get-SignArguments $mode $timestamp
Write-Host ("signtool: {0} | mode: {1} | timestamp: {2}" -f $signtool, $mode, $timestamp)

foreach ($item in $Target) {
    $resolved = (Resolve-Path -LiteralPath $item -ErrorAction Stop).Path
    Assert-Pe $resolved
    $arguments = @($common) + @($resolved)
    & $signtool $arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "signtool failed (exit $LASTEXITCODE) for $resolved (see the signtool output above)"
    }
    Assert-Signature $resolved -AllowUntrusted:$AllowUntrustedRoot
}
Write-Host ("Verified {0} signed and timestamped file(s)." -f $Target.Count)
