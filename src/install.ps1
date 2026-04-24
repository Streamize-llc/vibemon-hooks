# VibeMon installer for Windows
#
# Source: https://github.com/Streamize-llc/vibemon-hooks
# Docs:   https://vibemon.dev/docs
# This file is generated from src/install.ps1 by scripts/build.py.
#
# Usage:
#   # One-shot:
#   iwr -useb https://vibemon.dev/install.ps1 | iex; vibemon-install YOUR_API_KEY
#
#   # Pinned version (more cautious — review the script first):
#   iwr -useb https://github.com/Streamize-llc/vibemon-hooks/releases/download/vN/install.ps1 -OutFile install.ps1
#   .\install.ps1 -ApiKey YOUR_API_KEY
#
# Optional flags:
#   -NoCommitMsg          force commit message collection OFF
#   -CollectCommitMsg     force commit message collection ON

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [string]$ApiKey,
    [switch]$NoCommitMsg,
    [switch]$CollectCommitMsg
)

$ErrorActionPreference = "Stop"
$VIBEMON_VERSION = "__VIBEMON_VERSION__"

# ─── Embedded Python module bundle (built by scripts/build.py) ─────
# Contains: paths.py, lock.py, classify.py, extract.py, notify.py,
#           install.py, merge_*.py
# Format: gzip-compressed tar, base64-encoded. Reproducible (mtime=0).
$VIBEMON_BUNDLE_B64 = @'
__PYTHON_BUNDLE_BASE64__
'@

function Invoke-VibeMonInstall {
    [CmdletBinding()]
    param(
        [string]$ApiKey,
        [switch]$NoCommitMsg,
        [switch]$CollectCommitMsg
    )

    # ─── Preflight: find Python 3 ────────────────────────────────────
    $py = $null
    foreach ($cand in @("py", "python3", "python")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { $py = $cmd.Source; break }
    }
    if (-not $py) {
        Write-Error "Python 3 is required. Install from https://www.python.org/ and re-run."
        return 1
    }
    # `py` is the Python launcher — pass `-3` so it selects Python 3.
    $pyArgs = @()
    if ((Split-Path $py -Leaf) -ieq "py.exe") { $pyArgs = @("-3") }

    $VIBEMON_DIR = Join-Path $env:USERPROFILE ".vibemon"
    $apiKeyFile  = Join-Path $VIBEMON_DIR "api-key"

    # ─── API key resolution (re-install picks up existing) ──────────
    $isUpdate = $false
    if (-not $ApiKey) {
        if (Test-Path $apiKeyFile) {
            $ApiKey = (Get-Content $apiKeyFile -Raw).Trim()
            $isUpdate = $true
        } else {
            Write-Error "API key is required. Usage: vibemon-install YOUR_API_KEY"
            return 1
        }
    } elseif (Test-Path $apiKeyFile) {
        $isUpdate = $true
    }

    if ($isUpdate) {
        Write-Host "🐾 Updating VibeMon… (v$VIBEMON_VERSION)"
    } else {
        Write-Host "🐾 Installing VibeMon… (v$VIBEMON_VERSION)"
    }

    New-Item -ItemType Directory -Force -Path $VIBEMON_DIR | Out-Null

    # ─── Save API key, restrict ACL (rough chmod 0600 equivalent) ───
    Set-Content -Path $apiKeyFile -Value $ApiKey -NoNewline -Encoding ASCII
    try {
        & icacls $apiKeyFile /inheritance:r /grant:r "$($env:USERNAME):(F)" 2>&1 | Out-Null
    } catch {}
    Write-Host "  ✓ API key saved"

    # ─── Extract embedded Python bundle ─────────────────────────────
    if (-not $script:VIBEMON_BUNDLE_B64 -or $script:VIBEMON_BUNDLE_B64.Trim().Length -lt 100) {
        Write-Error "Embedded Python bundle is missing or empty — corrupt installer."
        return 1
    }
    $tarPath = Join-Path $VIBEMON_DIR "_bundle.tar.gz"
    [IO.File]::WriteAllBytes(
        $tarPath,
        [Convert]::FromBase64String($script:VIBEMON_BUNDLE_B64.Trim())
    )

    $extractPy = @"
import sys, tarfile, os
d = sys.argv[1]
with tarfile.open(os.path.join(d, '_bundle.tar.gz'), 'r:gz') as t:
    t.extractall(d)
os.unlink(os.path.join(d, '_bundle.tar.gz'))
"@
    & $py @pyArgs -c $extractPy $VIBEMON_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to extract Python bundle (exit $LASTEXITCODE)"
        return 1
    }
    Write-Host "  ✓ notify.py + helpers installed"

    # ─── Hand off to install.py for merge + test probe ──────────────
    $installPy = Join-Path $VIBEMON_DIR "install.py"
    $passArgs = @($installPy, $ApiKey, $VIBEMON_VERSION)
    if ($NoCommitMsg)      { $passArgs += "--no-commit-msg" }
    if ($CollectCommitMsg) { $passArgs += "--collect-commit-msg" }

    & $py @pyArgs @passArgs
    return $LASTEXITCODE
}

# Define a globally-scoped wrapper so users running the `iwr | iex`
# pattern can simply call `vibemon-install YOUR_API_KEY` afterward.
function global:vibemon-install {
    [CmdletBinding()]
    param(
        [Parameter(Position=0)][string]$ApiKey,
        [switch]$NoCommitMsg,
        [switch]$CollectCommitMsg
    )
    Invoke-VibeMonInstall -ApiKey $ApiKey -NoCommitMsg:$NoCommitMsg -CollectCommitMsg:$CollectCommitMsg
}

# If the script was invoked with -ApiKey directly (download + run),
# execute immediately and exit. Otherwise (piped via iex), the user
# will call vibemon-install themselves next.
if ($ApiKey) {
    exit (Invoke-VibeMonInstall -ApiKey $ApiKey -NoCommitMsg:$NoCommitMsg -CollectCommitMsg:$CollectCommitMsg)
}
