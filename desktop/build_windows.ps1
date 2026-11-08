# Build the Windows onedir release and (optionally) the Inno Setup installer.
#
#   powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1
#   powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1 -Installer
#   powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1 -Installer -Sign
#
# The release chain is split into stages so the compile stage never holds a certificate:
#   1. compile       : this script WITHOUT -Sign (no CIXI_SIGN_* value is read)
#   2. sign launcher : -Sign runs desktop\sign_windows.ps1 AFTER UPX and BEFORE Inno
#   3. package       : -PackageOnly on the already-signed folder (zip + Setup.exe)
#   4. sign setup    : -Sign on that stage signs Setup.exe too
#   5. manifest      : desktop\release_manifest.py writes SHA256SUMS over the final bytes
# Signing before UPX is useless: packing rewrites the PE and destroys the signature.
# Signing before Inno is required: the installer must embed the signed launcher verbatim.
#
# The build environment is separate from the project .venv on purpose: it contains only
# desktop/requirements-runtime.txt plus PyInstaller, so torch/transformers/pyarrow and
# the test tools cannot leak into the distributed folder.

param(
    [switch]$Clean,
    [switch]$NoZip,
    [switch]$Installer,
    # Wrap an already-built (and already-signed) folder: no venv, no PyInstaller, no UPX.
    [switch]$PackageOnly,
    [switch]$KeepWork,
    [switch]$RemoveBuildEnv,
    # UPX compression of the collected binaries is ON by default (it roughly halves the folder);
    # pass -NoUpx on a machine without the tool, or when shipping a build you cannot re-sign.
    [switch]$NoUpx,
    [switch]$SkipInstall,
    # Run the Authenticode stage at the two points where the bytes are final.
    [switch]$Sign,
    [string]$Version = '1.0.0'
)

$ErrorActionPreference = 'Stop'
# A pip self-upgrade is not needed to build and, under a non-interactive host, its
# pip-version check can block on the parent console. Leave the bootstrap pip alone.
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
# PyInstaller's default bootloader cache lives under %LOCALAPPDATA% and can be locked by
# a previous build or endpoint protection; a project-local cache keeps rebuilds clean.
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot '.pyinstaller-cache'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
# pip unpacks into %TEMP% and keeps its HTTP cache under %LOCALAPPDATA%. A restricted
# workspace denies both writes, and the symptom is a silent hang right after
# "Looking in indexes" - so temp and cache go inside the repo, and the cache is off.
$BuildTemp = Join-Path $RepoRoot 'build\tmp'
New-Item -ItemType Directory -Force -Path $BuildTemp | Out-Null
$env:TMP = $BuildTemp
$env:TEMP = $BuildTemp
$env:TMPDIR = $BuildTemp
$Venv = Join-Path $PSScriptRoot '.venv-build'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$DistRoot = Join-Path $RepoRoot 'dist'
$Dist = Join-Path $DistRoot 'CaiXiHui'
$Work = Join-Path $RepoRoot 'build\pyinstaller'
$Spec = Join-Path $PSScriptRoot 'caixihui.spec'
$Zip = Join-Path $DistRoot 'CaiXiHui-win64.zip'
$LauncherExe = Join-Path $Dist 'CaiXiHui.exe'
$SetupExe = Join-Path $DistRoot 'CaiXiHui-Setup.exe'
$OnlineSetupExe = Join-Path $DistRoot 'CaiXiHui-Online-Setup.exe'
$SignScript = Join-Path $PSScriptRoot 'sign_windows.ps1'
$IssScript = Join-Path $PSScriptRoot 'installer.iss'

# The installer stamps this same version into current-version and install.json. A version
# with a slash, a space or a prerelease suffix would make the pointer a path or break
# VersionInfoVersion, so it is refused before a ten-minute build starts.
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "-Version must be three numeric groups (for example 1.0.0), not '$Version'."
}
if ($PackageOnly -and $Clean) {
    throw '-PackageOnly wraps an existing folder; -Clean would delete it. Drop one of the two flags.'
}
if ($Sign -and -not (Test-Path $SignScript)) {
    throw "missing signing stage: $SignScript"
}

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

# The icon is stamped into both deliverables: PyInstaller copies it into CaiXiHui.exe and Inno
# Setup refuses to compile a file that is not really an ICO ("Resource update error: Icon file is
# invalid"). A PNG wearing an .ico name is shown happily by a browser and copied silently by
# PyInstaller, so the header is checked here - before the build spends ten minutes on it.
$Icon = Join-Path $RepoRoot 'backend\static\icon.ico'
if (-not (Test-Path $Icon)) {
    throw "missing icon: $Icon (regenerate it with tools\build_icon.py)"
}
$iconHead = [System.IO.File]::ReadAllBytes($Icon)[0..3]
if ($iconHead -join '.' -ne '0.0.1.0') {
    throw "$Icon is not an ICO (header must be 00 00 01 00): run .venv\Scripts\python.exe tools\build_icon.py"
}

if (-not $PackageOnly) {
    Write-Step "Build environment"
    # -Clean and -SkipInstall contradict each other: -Clean deletes the build environment below, and
    # -SkipInstall then refuses to reinstall it, so the run recreates an empty venv and fails at
    # "No module named PyInstaller" several minutes later with no connection to the real cause.
    # Measured: one wasted build. Refuse the pair at once instead.
    if ($Clean -and $SkipInstall) {
        throw '-Clean deletes the build environment, so -SkipInstall cannot follow it: drop one of the two flags.'
    }
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
        Invoke-Exe $VenvPython @('-m', 'pip', 'install', '--no-input', '--no-cache-dir', '--progress-bar', 'off', '--upgrade', 'setuptools==78.1.0', 'wheel')
        $RuntimeReq = Join-Path $PSScriptRoot 'requirements-runtime.txt'
        $BuildReq = Join-Path $PSScriptRoot 'requirements-build.txt'
        Invoke-Exe $VenvPython @('-m', 'pip', 'install', '--no-input', '--no-cache-dir', '--progress-bar', 'off', '--no-build-isolation', '-r', $RuntimeReq)
        Invoke-Exe $VenvPython @('-m', 'pip', 'install', '--no-input', '--no-cache-dir', '--progress-bar', 'off', '-r', $BuildReq)
    }

    Write-Step "PyInstaller onedir"
    if ($Clean) {
        Remove-Item -LiteralPath $Dist -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
    # PyInstaller is deliberately NOT given upx=True: when it cannot find the tool it compresses
    # nothing and says so only in a line most people scroll past, which would make the folder's
    # advertised size a guess. The explicit pass below fails by name instead.
    Invoke-Exe $VenvPython @('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', $DistRoot, '--workpath', $Work, $Spec)

    Write-Step "Prune unused platform/test payloads"
    Invoke-Exe $VenvPython @((Join-Path $PSScriptRoot 'prune_dist.py'), $Dist)

    if (-not $NoUpx) {
        Write-Step "Compress binaries with UPX"
        Invoke-Exe $VenvPython @((Join-Path $PSScriptRoot 'compress_dist.py'), $Dist)
    } else {
        Write-Host 'UPX compression SKIPPED (-NoUpx): the folder keeps its full size.'
    }

    if ($Sign) {
        # AFTER UPX: packing rewrites the PE and would destroy the signature. BEFORE Inno:
        # the installer has to embed these exact signed bytes.
        Write-Step "Sign the launcher before the installer wraps its bytes"
        & $SignScript -Target @($LauncherExe)
    }
} else {
    Write-Step "Package an already-built, already-signed folder"
    if (-not (Test-Path $LauncherExe)) {
        throw "-PackageOnly needs the built launcher at $LauncherExe; run the compile stage first."
    }
    Write-Host 'No venv, PyInstaller, prune, UPX or re-sign of the launcher in this stage.'
}

$folderBytes = Get-FolderSize $Dist
Write-Host ("Folder: {0}  ({1:N1} MB)" -f $Dist, ($folderBytes / 1MB))

if ($Installer -or $PackageOnly) {
    Write-Step "Inno Setup"
    # Version- and drive-agnostic on purpose. Hardcoding "Program Files\Inno Setup 6" misses a real
    # install: measured here, the tool lives at `E:\Inno Setup 7\ISCC.exe` -- a different major
    # version on a different drive -- and the build reported "not found" for an installer that was
    # installed. Set CIXI_ISCC to ISCC.exe if the tool is somewhere this walk does not cover.
    $candidates = @()
    if ($env:CIXI_ISCC) { $candidates += $env:CIXI_ISCC }
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($root) {
            $candidates += (Get-ChildItem -Path $root -Filter 'ISCC.exe' -Recurse -Depth 2 -ErrorAction SilentlyContinue |
                ForEach-Object { $_.FullName })
        }
    }
    foreach ($drive in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
        $candidates += (Get-ChildItem -Path (Join-Path $drive.Root 'Inno Setup *\ISCC.exe') -ErrorAction SilentlyContinue |
            ForEach-Object { $_.FullName })
    }
    $candidates += (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    $iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $iscc) {
        if ($Sign) {
            throw '-Sign needs ISCC.exe to produce a signed Setup.exe (checked Program Files, LOCALAPPDATA, drive roots, PATH and $env:CIXI_ISCC).'
        }
        Write-Warning 'ISCC.exe not found (checked Program Files, LOCALAPPDATA, every drive root for "Inno Setup *\ISCC.exe", PATH, and $env:CIXI_ISCC); the portable folder/zip is still usable.'
    } else {
        Write-Host ("Using ISCC: {0}" -f $iscc)
        # The same version lands in AppVersion, current-version and install.json.
        Invoke-Exe $iscc @("/DMyAppVersion=$Version", $IssScript)
        if (Test-Path $SetupExe) {
            # Inno's loader is always asInvoker and extracts into %TEMP% before the inner setup can
            # ask for UAC. On a machine that denies that write, the wizard never appears. Patching
            # the outer manifest to requireAdministrator makes Windows elevate the double-click
            # first; it must happen before -Sign, because signing covers the patched bytes.
            Invoke-Exe $VenvPython @((Join-Path $PSScriptRoot 'patch_manifest.py'), $SetupExe)
            Write-Host ("Setup:  {0}  ({1:N1} MB)" -f $SetupExe, ((Get-Item $SetupExe).Length / 1MB))
            if ($Sign) {
                Write-Step "Sign the installer after Inno embeds the signed bytes"
                $targets = @($SetupExe)
                if (Test-Path $OnlineSetupExe) { $targets += $OnlineSetupExe }
                & $SignScript -Target $targets
            }
        } elseif ($Sign) {
            throw "ISCC produced no $SetupExe; refusing to call an unsigned build signed."
        }
    }
}

if (-not $NoZip) {
    # Last: the zip must carry the SIGNED launcher, so it is made from the final folder,
    # never from the pre-signing bytes. A -PackageOnly stage overwrites the stale zip.
    Write-Step "Compressed zip from the final folder"
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
if ($Sign) {
    Write-Host 'Next stage: desktop\release_manifest.py --dist dist --version <version>'
}
