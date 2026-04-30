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
$VIBEMON_VERSION = "19"

# ─── Embedded Python module bundle (built by scripts/build.py) ─────
# Contains: paths.py, lock.py, classify.py, extract.py, notify.py,
#           install.py, merge_*.py
# Format: gzip-compressed tar, base64-encoded. Reproducible (mtime=0).
$VIBEMON_BUNDLE_B64 = @'
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
3H3uPnefu8+/98//B7SAibMAGAEA
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
