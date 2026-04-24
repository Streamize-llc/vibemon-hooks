# tests/run.ps1 — Single entry point for Windows CI / local validation.
# Mirror of tests/run.sh but skips the Unix-only dry-install step.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "=== Layer 1: build (must be reproducible) ==="
python scripts\build.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\build.py --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== Layer 2: pytest (unit + golden + canary + idempotent + parity) ==="
python -m pytest tests/ -v --tb=short
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "=== Layer 3: PowerShell AST parse on dist/install.ps1 ==="
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path "dist\install.ps1"),
    [ref]$tokens,
    [ref]$errors
)
if ($errors -and $errors.Count -gt 0) {
    foreach ($e in $errors) { Write-Error $e }
    exit 1
}
Write-Host "  ok dist\install.ps1 AST parses"

Write-Host ""
Write-Host "All checks green."
