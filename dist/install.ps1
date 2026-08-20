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
$VIBEMON_VERSION = "27"

# ─── Embedded Python module bundle (built by scripts/build.py) ─────
# Contains: paths.py, lock.py, classify.py, extract.py, notify.py,
#           install.py, merge_*.py
# Format: gzip-compressed tar, base64-encoded. Reproducible (mtime=0).
$VIBEMON_BUNDLE_B64 = @'
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
uFccrwBoAQA=
'@

function Invoke-VibeMonInstall {
    [CmdletBinding()]
    param(
        [string]$ApiKey,
        [switch]$NoCommitMsg,
        [switch]$CollectCommitMsg
    )

    # ─── Preflight: find Python 3 ────────────────────────────────────
    # The GUI installer's bundled interpreter wins (v25): consumer
    # machines often have NO system Python, and the daily auto-update
    # re-runs this script there — it must keep using the bundle instead
    # of failing the PATH probe.
    $py = $null
    $bundledPy = Join-Path $env:USERPROFILE ".vibemon\python\python.exe"
    if (Test-Path $bundledPy) {
        $py = $bundledPy
    } else {
        foreach ($cand in @("py", "python3", "python")) {
            $cmd = Get-Command $cand -ErrorAction SilentlyContinue
            if ($cmd) { $py = $cmd.Source; break }
        }
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

# Piped via `iwr | iex` with NO key but WITH a previous install on disk:
# this is the auto-update path — notify.py spawns exactly this command.
# Until v23 this case only defined the functions and did nothing, so
# Windows auto-update never actually updated. Run the update with the
# stored key. (`return`, not `exit` — exit would kill an interactive
# caller's shell session.)
$vibemonExistingKey = Join-Path (Join-Path $env:USERPROFILE ".vibemon") "api-key"
if (Test-Path $vibemonExistingKey) {
    $null = Invoke-VibeMonInstall
    return
}
