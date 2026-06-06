# Build VibeMonSetup.exe — Windows GUI installer (Phase 2).
#
# Stages the hash-pinned embeddable CPython + the hook runtime modules
# (module list comes from scripts/build.py — single source of truth),
# then compiles installer/windows/VibeMonSetup.iss with ISCC.
#
# Runs on windows-latest in CI (Inno Setup 6 is preinstalled on the
# GitHub runner image; choco fallback included for local use).
#
# Usage: pwsh installer/windows/build.ps1 [-OutDir dist-installer]
param([string]$OutDir = "dist-installer")

$ErrorActionPreference = "Stop"

$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VERSION = (Get-Content (Join-Path $ROOT "VERSION") -Raw).Trim()

# 3.12.10 is the FINAL 3.12 binary release — 3.12.11+ are source-only
# security releases with no embeddable artifact. Hash-pinned so a
# compromised mirror can't slip a different interpreter into the exe.
$PY_VERSION = "3.12.10"
$PY_SHA256  = "4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3"
$PY_URL     = "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip"

$stage = Join-Path $PSScriptRoot "stage"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path (Join-Path $stage "python") | Out-Null

# ─── 1. Embedded Python (pinned + verified) ──────────────────────────
$zip = Join-Path $stage "pyembed.zip"
Invoke-WebRequest -Uri $PY_URL -OutFile $zip -UseBasicParsing
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToUpper()
if ($hash -ne $PY_SHA256) {
    throw "embeddable python hash mismatch: got $hash, want $PY_SHA256"
}
Expand-Archive -Path $zip -DestinationPath (Join-Path $stage "python") -Force
Remove-Item $zip

# The embeddable distro FREEZES sys.path to the ._pth contents (the
# script directory is NOT auto-prepended). Append ".." so modules in
# ~/.vibemon are importable from ~/.vibemon/python/python.exe no matter
# how it is invoked. notify.py/install.py also self-insert their dir —
# this is the belt to that braces.
$pth = Get-ChildItem (Join-Path $stage "python") -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "._pth not found in embeddable distribution" }
Add-Content -Path $pth.FullName -Value ".."

# ─── 2. Hook runtime modules ─────────────────────────────────────────
$modules = & python (Join-Path $ROOT "scripts\build.py") --list-windows-bundle
if ($LASTEXITCODE -ne 0) { throw "build.py --list-windows-bundle failed" }
foreach ($m in $modules) {
    $name = "$m".Trim()
    if ($name) { Copy-Item (Join-Path $ROOT "src\$name") $stage }
}

# ─── 3. Compile ──────────────────────────────────────────────────────
$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    Write-Host "ISCC not found — installing Inno Setup via choco…"
    choco install innosetup -y --no-progress | Out-Null
}
if (-not (Test-Path $iscc)) { throw "ISCC.exe not found after install" }

$outAbs = Join-Path $ROOT $OutDir
New-Item -ItemType Directory -Force -Path $outAbs | Out-Null

& $iscc "/DAppVersion=$VERSION" "/DStageDir=$stage" "/DOutDir=$outAbs" `
    (Join-Path $PSScriptRoot "VibeMonSetup.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed ($LASTEXITCODE)" }

$exe = Join-Path $outAbs "VibeMonSetup.exe"
$exeHash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$exe.sha256" -Value "$exeHash  VibeMonSetup.exe" -NoNewline -Encoding ascii

$sizeMB = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "built $exe (v$VERSION, ${sizeMB}MB)"
