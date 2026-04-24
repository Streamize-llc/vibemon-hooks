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
$VIBEMON_VERSION = "17"

# ─── Embedded Python module bundle (built by scripts/build.py) ─────
# Contains: paths.py, lock.py, classify.py, extract.py, notify.py,
#           install.py, merge_*.py
# Format: gzip-compressed tar, base64-encoded. Reproducible (mtime=0).
$VIBEMON_BUNDLE_B64 = @'
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
/NY//x+oyR95ABgBAA==
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
