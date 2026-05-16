param(
    [string[]] $RequiredEnv = @(
        "APP_ENV",
        "API_SECRET_KEY",
        "OPENAI_API_KEY"
    ),
    [string[]] $OptionalEnv = @(
        "DATABASE_URL"
    )
)

$ErrorActionPreference = "Stop"

function Test-CommandAvailable {
    param([string] $Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return "present"
    }
    return "missing"
}

function Test-EnvPresent {
    param([string] $Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return "missing"
    }
    return "present"
}

$pythonVersion = (& python --version 2>&1)

Write-Output "supportFAQagent runtime preflight"
Write-Output "python=$pythonVersion"
Write-Output "psql=$(Test-CommandAvailable -Name 'psql')"
Write-Output "docker=$(Test-CommandAvailable -Name 'docker')"
Write-Output "env_file=$(if (Test-Path '.env') { 'present' } else { 'missing' })"

foreach ($name in $RequiredEnv) {
    Write-Output "$name=$(Test-EnvPresent -Name $name)"
}

foreach ($name in $OptionalEnv) {
    Write-Output "$name=$(Test-EnvPresent -Name $name) optional"
}

Write-Output "note=secret values are intentionally not printed"
