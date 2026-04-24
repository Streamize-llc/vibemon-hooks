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
$VIBEMON_VERSION = "18"

# ─── Embedded Python module bundle (built by scripts/build.py) ─────
# Contains: paths.py, lock.py, classify.py, extract.py, notify.py,
#           install.py, merge_*.py
# Format: gzip-compressed tar, base64-encoded. Reproducible (mtime=0).
$VIBEMON_BUNDLE_B64 = @'
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
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
