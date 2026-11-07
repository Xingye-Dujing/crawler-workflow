# Build the small online installer (CaiXiHui-Online-Setup.exe).
#
# It uses the same desktop build environment as the offline app (PyInstaller only), but the spec
# carries just the component core and the local page server -- no GUI toolkit at all -- so the
# result is a few megabytes rather than a second full application. UPX is off on purpose (spec).
#
#   powershell -ExecutionPolicy Bypass -File desktop\bootstrap\build.ps1

param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$VenvPython = Join-Path $RepoRoot 'desktop\.venv-build\Scripts\python.exe'
$Spec = Join-Path $PSScriptRoot 'installer.spec'
$Dist = Join-Path $RepoRoot 'dist'
$Work = Join-Path $RepoRoot 'build\pyinstaller-bootstrap'

if (-not (Test-Path $VenvPython)) {
    throw "missing build environment: $VenvPython (run desktop\build_windows.ps1 once, or create the venv)"
}
if ($Clean) {
    Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
}

$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.pyinstaller-cache'
& $VenvPython -m PyInstaller --noconfirm --clean --distpath $Dist --workpath $Work $Spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit $LASTEXITCODE)"
}

$Exe = Join-Path $Dist 'CaiXiHui-Online-Setup.exe'
if (-not (Test-Path $Exe)) {
    throw "expected output not found: $Exe"
}
$Size = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
Write-Host ""
Write-Host "Online installer: $Exe ($Size MB)" -ForegroundColor Green
