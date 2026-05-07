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
$VIBEMON_VERSION = "20"

# ─── Embedded Python module bundle (built by scripts/build.py) ─────
# Contains: paths.py, lock.py, classify.py, extract.py, notify.py,
#           install.py, merge_*.py
# Format: gzip-compressed tar, base64-encoded. Reproducible (mtime=0).
$VIBEMON_BUNDLE_B64 = @'
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
+9x9/iN8/j+rWZrQABgBAA==
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
