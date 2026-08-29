param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$ComposeFile = Join-Path $Root "docker-compose.fullstack.yml"
$BackendDir = Join-Path $Root "backend"
$WebDir = Join-Path $Root "web"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Wait-Healthy([string]$ContainerName, [int]$TimeoutSeconds = 120) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        $status = docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $ContainerName 2>$null
        if ($LASTEXITCODE -eq 0 -and $status -eq "healthy") {
            Write-Host "$ContainerName is healthy." -ForegroundColor Green
            return
        }

        if ($LASTEXITCODE -eq 0 -and $status -eq "running") {
            Write-Host "$ContainerName is running." -ForegroundColor Green
            return
        }

        Start-Sleep -Seconds 2
    }

    throw "Timed out waiting for $ContainerName to become healthy."
}

Write-Step "Checking Docker Desktop"
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running. Start Docker Desktop first, then run this script again."
}

Write-Step "Starting MySQL, PgVector, and MinIO"
docker compose -f $ComposeFile up -d
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start Docker services."
}

Write-Step "Waiting for infrastructure"
Wait-Healthy "deepdesk-mysql"
Wait-Healthy "deepdesk-pgvector"
Wait-Healthy "deepdesk-minio" 60

Write-Step "Preparing full-stack environment"
$env:PERSISTENCE_MODE = "database"
$env:DATABASE_URL = "mysql+pymysql://deepdesk:deepdesk_dev@127.0.0.1:3307/deepdesk?charset=utf8mb4"
$env:MINIO_ENDPOINT = "http://127.0.0.1:9000"
$env:MINIO_ACCESS_KEY = "deepdesk"
$env:MINIO_SECRET_KEY = "deepdesk_dev_secret"
$env:MINIO_BUCKET = "rag-test2"
$env:MINIO_SECURE = "false"
$env:MINIO_PUBLIC_READ = "true"
$env:VECTOR_DATABASE_URL = "postgresql+psycopg://deepdesk:deepdesk_dev@127.0.0.1:5434/deepdesk_vectors"
$env:TASK_MANAGER_MODE = "local"

Write-Step "Applying database migrations"
Push-Location $BackendDir
try {
    python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic migration failed."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $WebDir "node_modules"))) {
    Write-Step "Installing frontend dependencies"
    Push-Location $WebDir
    try {
        npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed."
        }
    }
    finally {
        Pop-Location
    }
}

Write-Step "Starting backend"
$backendCommand = "Set-Location '$BackendDir'; python -m uvicorn app.main:app --host 127.0.0.1 --port 8888"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    $backendCommand
)

Write-Step "Starting frontend"
$frontendCommand = "Set-Location '$WebDir'; npm run dev"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    $frontendCommand
)

Write-Host ""
Write-Host "DeepDesk is starting." -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Backend:  http://127.0.0.1:8888"
Write-Host "MinIO:    http://127.0.0.1:9001"

if (-not $NoBrowser) {
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:5173"
}
