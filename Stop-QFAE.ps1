[CmdletBinding()]
param(
    [switch]$KeepContainers,
    [switch]$Preview
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendNeedle = (Join-Path $projectRoot "backend\.venv\Scripts\python.exe").ToLowerInvariant()
$frontendNeedle = (Join-Path $projectRoot "frontend\node_modules").ToLowerInvariant()

function Write-Step {
    param([string]$Message)
    Write-Host "[Q-FAE] $Message" -ForegroundColor Cyan
}

function Process-CommandLine {
    param([object]$Process)
    if ($null -eq $Process.CommandLine) {
        return ""
    }
    return $Process.CommandLine.ToLowerInvariant()
}

Set-Location -LiteralPath $projectRoot

# Ask the backend to disconnect the provider stream and cancel its market-open
# timer before terminating the development server. Failure is harmless when the
# backend is already stopped or still starting.
try {
    $null = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8000/api/v1/health" `
        -UseBasicParsing `
        -TimeoutSec 2
    if ($Preview) {
        Write-Step "Would disconnect the live feed and cancel any scheduled start."
    }
    else {
        Write-Step "Disconnecting the live feed and cancelling scheduled start..."
        $null = Invoke-RestMethod `
            -Method Post `
            -Uri "http://127.0.0.1:8000/api/v1/market/live/stop" `
            -TimeoutSec 10
    }
}
catch {
    Write-Step "Backend is already stopped or did not accept the shutdown request."
}

$allProcesses = @(Get-CimInstance Win32_Process)
$byId = @{}
foreach ($process in $allProcesses) {
    $byId[[int]$process.ProcessId] = $process
}

$serviceProcesses = @(
    $allProcesses | Where-Object {
        $commandLine = Process-CommandLine $_
        (
            $_.Name -ieq "python.exe" -and
            $commandLine.Contains($backendNeedle) -and
            $commandLine.Contains("uvicorn") -and
            $commandLine.Contains("app.main:app")
        ) -or (
            $_.Name -ieq "node.exe" -and
            $commandLine.Contains($frontendNeedle) -and
            $commandLine.Contains("vite")
        )
    }
)

$serviceIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($process in $serviceProcesses) {
    $null = $serviceIds.Add([int]$process.ProcessId)
}

# Include child helpers such as the uvicorn reloader and Vite/esbuild workers.
$addedChild = $true
while ($addedChild) {
    $addedChild = $false
    foreach ($process in $allProcesses) {
        if ($serviceIds.Contains([int]$process.ParentProcessId) -and -not $serviceIds.Contains([int]$process.ProcessId)) {
            $null = $serviceIds.Add([int]$process.ProcessId)
            $addedChild = $true
        }
    }
}

# Launcher-created terminals use -NoExit; include those parents so no minimized
# empty PowerShell windows remain. A manually opened VS Code terminal is not
# matched and therefore stays open.
$terminalIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($process in $serviceProcesses) {
    $parentId = [int]$process.ParentProcessId
    while ($parentId -gt 0 -and $byId.ContainsKey($parentId)) {
        $parent = $byId[$parentId]
        $commandLine = Process-CommandLine $parent
        if (
            $parent.Name -ieq "powershell.exe" -and
            $commandLine.Contains("-noexit") -and
            (
                $commandLine.Contains("uvicorn app.main:app") -or
                ($commandLine.Contains("npm.cmd") -and $commandLine.Contains("run dev"))
            )
        ) {
            $null = $terminalIds.Add([int]$parent.ProcessId)
            break
        }
        $parentId = [int]$parent.ParentProcessId
    }
}

if ($serviceIds.Count -eq 0) {
    Write-Step "Backend and frontend processes are already stopped."
}
else {
    Write-Step "Stopping backend and frontend processes..."
    foreach ($processId in $serviceIds) {
        if ($Preview) {
            Write-Step "Would stop Q-FAE service process $processId."
        }
        else {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $Preview) {
        Start-Sleep -Milliseconds 500
    }
    foreach ($processId in $terminalIds) {
        if ($Preview) {
            Write-Step "Would close Q-FAE service terminal process $processId."
        }
        else {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not $KeepContainers) {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            if ($Preview) {
                Write-Step "Would stop the Q-FAE Redis and PostgreSQL containers."
            }
            else {
                Write-Step "Stopping Redis and PostgreSQL containers..."
                & docker compose stop redis postgres
                if ($LASTEXITCODE -ne 0) {
                    throw "Docker Compose could not stop the Q-FAE data services."
                }
            }
        }
        else {
            Write-Step "Docker Engine is already stopped."
        }
    }
    else {
        Write-Step "Docker CLI is unavailable; containers were not running through this shell."
    }
}
else {
    Write-Step "Leaving Redis and PostgreSQL running as requested."
}

Write-Host ""
if ($Preview) {
    Write-Host "Preview complete. No Q-FAE process or container was stopped." -ForegroundColor Yellow
}
else {
    Write-Host "Q-FAE is stopped. PostgreSQL and Redis volumes were preserved." -ForegroundColor Green
}

