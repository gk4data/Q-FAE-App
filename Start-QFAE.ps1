[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Join-Path $projectRoot "backend"
$frontendRoot = Join-Path $projectRoot "frontend"
$pythonPath = Join-Path $backendRoot ".venv\Scripts\python.exe"

function Write-Step {
    param([string]$Message)
    Write-Host "[Q-FAE] $Message" -ForegroundColor Cyan
}

function Test-HttpEndpoint {
    param([string]$Uri)
    try {
        $null = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
        return $true
    }
    catch {
        return $false
    }
}

function Test-ListeningPort {
    param([int]$Port)
    return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Wait-ForEndpoint {
    param(
        [string]$Uri,
        [int]$TimeoutSeconds = 45
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-HttpEndpoint -Uri $Uri) {
            return $true
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Test-DockerEngine {
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".env"))) {
    throw "Missing $projectRoot\.env. Create it from .env.example before starting Q-FAE."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install Docker Desktop and reopen PowerShell."
}

if (-not (Test-DockerEngine)) {
    Write-Step "Starting Docker Desktop..."
    $dockerDesktopCandidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Docker\Docker Desktop.exe")
    )
    $dockerDesktopPath = $dockerDesktopCandidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
        Select-Object -First 1

    if (-not $dockerDesktopPath) {
        throw "Docker Desktop is installed but its executable could not be located. Start Docker Desktop manually and rerun this launcher."
    }

    Start-Process -FilePath $dockerDesktopPath -WindowStyle Hidden
    $dockerDeadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 2
        if (Test-DockerEngine) {
            break
        }
    } while ((Get-Date) -lt $dockerDeadline)

    if (-not (Test-DockerEngine)) {
        throw "Docker Engine did not become ready within three minutes. Check Docker Desktop and rerun the launcher."
    }
}

Write-Step "Starting Redis and PostgreSQL..."
& docker compose up -d redis postgres
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose could not start Redis and PostgreSQL."
}

$databaseDeadline = (Get-Date).AddSeconds(60)
do {
    & docker compose exec -T postgres pg_isready -h 127.0.0.1 *> $null
    if ($LASTEXITCODE -eq 0) {
        break
    }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $databaseDeadline)

if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL did not become ready within one minute. Run 'docker compose ps' for details."
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Backend environment not found at $pythonPath. Follow the one-time backend setup in README.md, then rerun this launcher."
}

Write-Step "Applying pending database migrations..."
Push-Location -LiteralPath $backendRoot
try {
    & $pythonPath -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed."
    }
}
finally {
    Pop-Location
}

$backendHealth = "http://127.0.0.1:8000/api/v1/health"
if (Test-HttpEndpoint -Uri $backendHealth) {
    Write-Step "Backend is already running."
}
else {
    if (Test-ListeningPort -Port 8000) {
        throw "Port 8000 is already occupied by another process. Stop it and rerun this launcher."
    }
    Write-Step "Starting backend in a minimized service window..."
    $backendCommand = "& '$pythonPath' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-NoExit", "-Command", $backendCommand) `
        -WorkingDirectory $backendRoot `
        -WindowStyle Minimized
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    throw "npm was not found. Install Node.js and reopen PowerShell."
}

$frontendUrl = "http://localhost:3000/"
if (Test-HttpEndpoint -Uri $frontendUrl) {
    Write-Step "Frontend is already running."
}
else {
    if (Test-ListeningPort -Port 3000) {
        throw "Port 3000 is already occupied by another process. Stop it and rerun this launcher."
    }
    Write-Step "Starting frontend in a minimized service window..."
    $frontendCommand = "& '$($npmCommand.Source)' run dev"
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-NoExit", "-Command", $frontendCommand) `
        -WorkingDirectory $frontendRoot `
        -WindowStyle Minimized
}

Write-Step "Waiting for Q-FAE services..."
$backendReady = Wait-ForEndpoint -Uri $backendHealth -TimeoutSeconds 45
$frontendReady = Wait-ForEndpoint -Uri $frontendUrl -TimeoutSeconds 45

if (-not $backendReady -or -not $frontendReady) {
    $failedServices = @()
    if (-not $backendReady) {
        $failedServices += "backend ($backendHealth)"
    }
    if (-not $frontendReady) {
        $failedServices += "frontend ($frontendUrl)"
    }
    throw "Q-FAE startup timed out waiting for: $($failedServices -join ', '). Restore the corresponding minimized service window and inspect its errors."
}

Write-Host ""
Write-Host "Q-FAE is ready: $frontendUrl" -ForegroundColor Green
Write-Host "Backend health: $backendHealth" -ForegroundColor DarkGray

if (-not $NoBrowser) {
    Start-Process $frontendUrl
}

