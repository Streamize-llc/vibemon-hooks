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
$VIBEMON_VERSION = "16"

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
