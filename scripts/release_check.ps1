# scripts/release_check.ps1 — pre-tag validator for hello-agent-2 releases.
#
# Usage (from the worktree root, in PowerShell 5.1+):
#     .\scripts\release_check.ps1                 # auto-detect version from hello_agent\__init__.py
#     .\scripts\release_check.ps1 -Version 0.3.0  # override the expected version
#
# Exits 0 if every gate passes. Exits 1 with a diagnostic on the first failure.
# Prints a summary table at the end so the human can see exactly what changed.
#
# Gates:
#   1. Working directory is the repo root (looks for pyproject.toml).
#   2. Ruff lint is clean (hello_agent/, scripts/, tests/).
#   3. Full pytest suite is green.
#   4. hello_agent/__version__ matches the requested version.
#   5. pyproject.toml [project] version matches the requested version.
#   6. The git tag (v<version>) does not already exist locally or on origin.
#   7. The worktree is clean (no untracked / unstaged changes that aren't .gitignore-d).
#   8. CHANGELOG.md has an entry for the requested version.
#
# Why a PowerShell script and not a Makefile / Justfile? The primary platform
# is Windows; bash on Windows is a second-class citizen. PowerShell is always
# present. The script also runs fine in PowerShell 7+ on macOS/Linux if you
# ever cross-build.

[CmdletBinding()]
param(
    [string]$Version = "",
    [int]$PytestTimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ─── locate the repo root ────────────────────────────────────────────────────

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $RepoRoot

if (-not (Test-Path "pyproject.toml")) {
    Write-Host "FAIL: pyproject.toml not found at $RepoRoot" -ForegroundColor Red
    exit 1
}

Write-Host "hello-agent-2 release check" -ForegroundColor Cyan
Write-Host ("=" * 40) -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host ""

# ─── helpers ────────────────────────────────────────────────────────────────

$Results = New-Object System.Collections.Generic.List[object]

function Run-Gate {
    param(
        [string]$Name,
        [scriptblock]$Block
    )
    Write-Host "[...] $Name" -NoNewline
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $output = & $Block 2>&1 | Out-String
        $sw.Stop()
        if ($LASTEXITCODE -ne 0) {
            Write-Host "`r[FAIL] $Name  ($($sw.Elapsed.TotalSeconds.ToString('0.0'))s)" -ForegroundColor Red
            Write-Host $output
            $Results.Add([pscustomobject]@{ Gate = $Name; Status = "FAIL"; Seconds = $sw.Elapsed.TotalSeconds })
            exit 1
        } else {
            Write-Host "`r[ OK ] $Name  ($($sw.Elapsed.TotalSeconds.ToString('0.0'))s)" -ForegroundColor Green
            $Results.Add([pscustomobject]@{ Gate = $Name; Status = "OK"; Seconds = $sw.Elapsed.TotalSeconds })
        }
    } catch {
        $sw.Stop()
        Write-Host "`r[FAIL] $Name  ($($sw.Elapsed.TotalSeconds.ToString('0.0'))s)" -ForegroundColor Red
        Write-Host $_.Exception.Message
        $Results.Add([pscustomobject]@{ Gate = $Name; Status = "FAIL"; Seconds = $sw.Elapsed.TotalSeconds })
        exit 1
    }
}

# ─── gate 1: determine the expected version if not provided ──────────────────

if ([string]::IsNullOrWhiteSpace($Version)) {
    $initPy = Get-Content "hello_agent/__init__.py" -Raw -Encoding UTF8
    if ($initPy -match '^__version__\s*=\s*["'']([^"'']+)["'']') {
        $Version = $Matches[1]
    } else {
        Write-Host "FAIL: could not parse __version__ from hello_agent/__init__.py" -ForegroundColor Red
        exit 1
    }
}
Write-Host "Expected version: $Version"
Write-Host ""

# ─── gate 2: ruff ────────────────────────────────────────────────────────────

Run-Gate "ruff check hello_agent/ scripts/ tests/" {
    uv run ruff check hello_agent/ scripts/ tests/
    return $LASTEXITCODE
}

# ─── gate 3: full pytest ────────────────────────────────────────────────────

Run-Gate "pytest -q (full suite)" {
    # We pipe stdout to a log file so the table doesn't drown in dots.
    $logPath = Join-Path $env:TEMP "hello_agent_release_pytest.log"
    uv run pytest -q --timeout=$PytestTimeoutSeconds *> $logPath
    $exit = $LASTEXITCODE
    if ($exit -ne 0) {
        Get-Content $logPath -Tail 80
    } else {
        $summaryLine = Select-String -Path $logPath -Pattern "passed|failed|error" -RawErrorAction SilentlyContinue |
            Select-Object -Last 1
        if ($summaryLine) {
            Write-Host "       $summaryLine"
        }
    }
    return $exit
}

# ─── gate 4: hello_agent.__version__ ────────────────────────────────────────

Run-Gate "hello_agent.__version__ == $Version" {
    $cmd = 'import hello_agent; print(hello_agent.__version__)'
    $actual = uv run python -c $cmd 2>&1 | Out-String
    $actual = $actual.Trim()
    if ($actual -ne $Version) {
        Write-Host "       hello_agent reports $actual, expected $Version" -ForegroundColor Red
        return 1
    }
    Write-Host "       hello_agent reports $actual"
    return 0
}

# ─── gate 5: pyproject.toml version ─────────────────────────────────────────

Run-Gate "pyproject.toml version == $Version" {
    $toml = Get-Content "pyproject.toml" -Raw -Encoding UTF8
    if ($toml -match '(?m)^version\s*=\s*["'']([^"'']+)["'']') {
        $actual = $Matches[1]
    } else {
        Write-Host "       could not find version in pyproject.toml" -ForegroundColor Red
        return 1
    }
    if ($actual -ne $Version) {
        Write-Host "       pyproject.toml version is $actual, expected $Version" -ForegroundColor Red
        return 1
    }
    Write-Host "       pyproject.toml version is $actual"
    return 0
}

# ─── gate 6: tag must not already exist ─────────────────────────────────────

Run-Gate "tag v$Version does not exist" {
    $tag = "v$Version"
    $localExists = git rev-parse -q --verify "refs/tags/$tag" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "       local tag $tag already exists" -ForegroundColor Red
        return 1
    }
    $remoteExists = git ls-remote origin "refs/tags/$tag" 2>$null | Select-String "$tag$"
    if ($remoteExists) {
        Write-Host "       remote tag $tag already exists on origin" -ForegroundColor Red
        return 1
    }
    Write-Host "       neither local nor origin has $tag"
    return 0
}

# ─── gate 7: worktree is clean (modulo .gitignore) ───────────────────────────

Run-Gate "git worktree clean" {
    $status = git status --porcelain 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "       git status failed" -ForegroundColor Red
        return 1
    }
    $lines = @($status | Where-Object { $_ })
    if ($lines.Count -gt 0) {
        Write-Host "       uncommitted changes present:" -ForegroundColor Red
        $lines | ForEach-Object { Write-Host "         $_" }
        return 1
    }
    Write-Host "       working tree is clean"
    return 0
}

# ─── gate 8: CHANGELOG has an entry for this version ─────────────────────────

Run-Gate "CHANGELOG.md has ## [$Version]" {
    if (-not (Test-Path "docs/CHANGELOG.md")) {
        Write-Host "       docs/CHANGELOG.md not found" -ForegroundColor Red
        return 1
    }
    $changelog = Get-Content "docs/CHANGELOG.md" -Raw -Encoding UTF8
    if ($changelog -notmatch [regex]::Escape("## [$Version]")) {
        Write-Host "       no '## [$Version]' header found" -ForegroundColor Red
        return 1
    }
    Write-Host "       docs/CHANGELOG.md has the entry"
    return 0
}

# ─── summary ────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "Summary" -ForegroundColor Cyan
Write-Host ("=" * 40) -ForegroundColor Cyan
$Results | ForEach-Object {
    $color = if ($_.Status -eq "OK") { "Green" } else { "Red" }
    Write-Host ("  {0,-50} {1,-6} {2,6}s" -f $_.Gate, $_.Status, $_.Seconds.ToString('0.0')) -ForegroundColor $color
}
Write-Host ""
Write-Host "All gates passed. Safe to tag v$Version and push." -ForegroundColor Green
exit 0