<#
.SYNOPSIS
    Run the gated PostgreSQL integration suite locally against a disposable
    pgvector database started by docker-compose.test.yml.

.DESCRIPTION
    The integration tests skip unless PHASE0_TEST_DATABASE_URL is set. This
    script starts a throwaway Postgres, exports the required env vars, applies
    migrations, runs the suite, and tears the database down again. It does NOT
    change the skip gating: without this script (or the env vars) the suite
    still skips.

    Requires: docker + docker compose, and `pip install -e ".[dev]"`.

.PARAMETER KeepDb
    Leave the disposable Postgres running after the suite finishes.

.EXAMPLE
    ./scripts/run_integration_tests.ps1
    ./scripts/run_integration_tests.ps1 -KeepDb
#>
[CmdletBinding()]
param(
    [switch]$KeepDb,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $root "docker-compose.test.yml"

# Lab-only, disposable connection. Must match docker-compose.test.yml and keep a
# database name that matches (test|phase0|disposable) for the conftest guard.
$env:PHASE0_TEST_DATABASE_URL = "postgresql://postgres:throwaway_test_password@127.0.0.1:55432/supportfaq_phase0"
$env:PHASE0_TEST_DATABASE_DISPOSABLE = "true"
$env:DATABASE_URL = $env:PHASE0_TEST_DATABASE_URL
$env:PERSISTENCE_HASH_SECRET = "local-phase0-test-secret"
$env:PERSISTENCE_HASH_VERSION = "hmac-sha256-v1"

function Invoke-Teardown {
    if ($KeepDb) {
        Write-Host "KeepDb set; leaving disposable Postgres running."
        return
    }
    Write-Host "Tearing down disposable Postgres..."
    docker compose -f $composeFile down -v | Out-Null
}

try {
    Write-Host "Starting disposable Postgres (pgvector)..."
    docker compose -f $composeFile up -d

    Write-Host "Waiting for Postgres to become healthy..."
    $status = "unknown"
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $status = docker inspect -f '{{.State.Health.Status}}' supportfaq_postgres_test 2>$null
        } catch {
            $status = "unknown"
        }
        if ($status -eq "healthy") { break }
        Start-Sleep -Seconds 2
    }
    if ($status -ne "healthy") {
        throw "Postgres did not become healthy in time."
    }

    Write-Host "Applying migrations..."
    python -m scripts.migrate apply
    if ($LASTEXITCODE -ne 0) { throw "Migrations failed." }

    Write-Host "Running integration suite..."
    python -m pytest tests/integration -q @PytestArgs
    $suiteExit = $LASTEXITCODE
}
finally {
    Invoke-Teardown
}

exit $suiteExit
