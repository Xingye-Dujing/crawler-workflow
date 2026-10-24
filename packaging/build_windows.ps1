# Build the Windows onedir release and (optionally) the Inno Setup installer.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Installer
#
# The build environment is separate from the project .venv on purpose: it contains only
# packaging/requirements-runtime.txt plus PyInstaller, so torch/transformers/pyarrow and
# the test tools cannot leak into the distributed folder.

param(
    [switch]$Clean,
    [switch]$NoZip,
    [switch]$Installer,
    [switch]$KeepWork,
    [switch]$RemoveBuildEnv,
    [switch]$Upx,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
# A pip self-upgrade is not needed to build and, under a non-interactive host, its
# pip-version check can block on the parent console. Leave the bootstrap pip alone.
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
# PyInstaller's default bootloader cache lives under %LOCALAPPDATA% and can be locked by
# a previous build or endpoint protection; a project-local cache keeps rebuilds clean.
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.pyinstaller-cache'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Venv = Join-Path $PSScriptRoot '.venv-build'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$DistRoot = Join-Path $RepoRoot 'dist'
$Dist = Join-Path $DistRoot 'CaiXiHui'
$Work = Join-Path $RepoRoot 'build\pyinstaller'
$Spec = Join-Path $PSScriptRoot 'caixihui.spec'
$Zip = Join-Path $DistRoot 'CaiXiHui-win64.zip'

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

# Run a native command with Start-Process rather than `&`. Calling a Python child directly
# with `&` can block forever when this script is launched from a non-interactive host
# (observed while building: pip printed the first line and never returned), because of how
# the inherited console/stdin is wired. Start-Process gives the child a normal console and
# returns a real exit code.
function Invoke-Exe([string]$Exe, [string[]]$ArgList) {
    $safe = $ArgList | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }
    $proc = Start-Process -FilePath $Exe -ArgumentList $safe -Wait -NoNewWindow -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "command failed (exit $($proc.ExitCode)): $Exe $($safe -join ' ')"
    }
}

function Get-FolderSize([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    return (Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
}

Write-Step "Build environment"
$BasePython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $BasePython)) {
    $BasePython = (Get-Command python -ErrorAction Stop).Source
}
if ($Clean -and (Test-Path $Venv)) {
    Remove-Item -LiteralPath $Venv -Recurse -Force
}
if (-not (Test-Path $VenvPython)) {
    Invoke-Exe $BasePython @('-m', 'venv', $Venv)
}
# jieba/snownlp ship as source distributions; without a prepared build environment pip
# spends a long time in an isolated build env on a fresh machine. setuptools+wheel make
# --no-build-isolation deterministic (and wheels are unaffected by the flag).
if ($SkipInstall) {
    Write-Host 'Skipping dependency installation (-SkipInstall).'
} else {
    Invoke-Exe $VenvPython @('-m', 'pip', 'install', '--no-input', '--progress-bar', 'off', '--upgrade', 'setuptools==78.1.0', 'wheel')
    $RuntimeReq = Join-Path $PSScriptRoot 'requirements-runtime.txt'
    $BuildReq = Join-Path $PSScriptRoot 'requirements-build.txt'
    Invoke-Exe $VenvPython @('-m', 'pip', 'install', '--no-input', '--progress-bar', 'off', '--no-build-isolation', '-r', $RuntimeReq)
    Invoke-Exe $VenvPython @('-m', 'pip', 'install', '--no-input', '--progress-bar', 'off', '-r', $BuildReq)
}

Write-Step "PyInstaller onedir"
if ($Clean) {
    Remove-Item -LiteralPath $Dist -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
}
if ($Upx) {
    $env:CAIXIHUI_UPX = '1'
    Write-Host 'UPX compression is ON (smaller folder, more antivirus false positives possible).'
} else {
    Remove-Item Env:CAIXIHUI_UPX -ErrorAction SilentlyContinue
}
Invoke-Exe $VenvPython @('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', $DistRoot, '--workpath', $Work, $Spec)

Write-Step "Prune unused platform/test payloads"
Invoke-Exe $VenvPython @((Join-Path $PSScriptRoot 'prune_dist.py'), $Dist)

$folderBytes = Get-FolderSize $Dist
Write-Host ("Folder: {0}  ({1:N1} MB)" -f $Dist, ($folderBytes / 1MB))

if (-not $NoZip) {
    Write-Step "Compressed zip"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path $Zip) { Remove-Item -LiteralPath $Zip -Force }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $Dist,
        $Zip,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $true
    )
    $zipBytes = (Get-Item $Zip).Length
    Write-Host ("Zip:    {0}  ({1:N1} MB)" -f $Zip, ($zipBytes / 1MB))
}

if ($Installer) {
    Write-Step "Inno Setup"
    $candidates = @()
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    }
    $iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $iscc) {
        Write-Warning 'Inno Setup 6 not found; the portable folder/zip is still usable.'
    } else {
        & $iscc (Join-Path $PSScriptRoot 'installer.iss')
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
        $setup = Join-Path $DistRoot 'CaiXiHui-Setup.exe'
        if (Test-Path $setup) {
            Write-Host ("Setup:  {0}  ({1:N1} MB)" -f $setup, ((Get-Item $setup).Length / 1MB))
        }
    }
}

if (-not $KeepWork) {
    Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
}
if ($RemoveBuildEnv) {
    Write-Step "Remove build environment"
    Remove-Item -LiteralPath $Venv -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Step "Done"
Write-Host "Portable folder: $Dist"
if (-not $NoZip) { Write-Host "Distribution zip: $Zip" }
