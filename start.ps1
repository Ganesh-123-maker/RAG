param(
    [switch]$Rebuild,
    [switch]$Logs,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"

$banner = @"

  ██████╗  █████╗  ██████╗
  ██╔══██╗██╔══██╗██╔════╝
  ██████╔╝███████║██║  ███╗
  ██╔══██╗██╔══██║██║   ██║
  ██║  ██║██║  ██║╚██████╔╝
  ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝
  Agentic RAG Knowledge Assistant

"@
Write-Host $banner -ForegroundColor Cyan

# ── Stop mode ─────────────────────────────────────────────────────────────────
if ($Stop) {
    Write-Host "Stopping all services..." -ForegroundColor Yellow
    docker compose down
    Write-Host "[+] All services stopped." -ForegroundColor Green
    exit 0
}

# ── Logs mode ─────────────────────────────────────────────────────────────────
if ($Logs) {
    docker compose logs -f --tail=100
    exit 0
}

# ── Pre-flight checks ─────────────────────────────────────────────────────────

# 1. Docker running?
try {
    docker info *>$null 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker not running" }
    Write-Host "[+] Docker is running" -ForegroundColor Green
} catch {
    Write-Host "" 
    Write-Host "[!] Docker Desktop is not running." -ForegroundColor Red
    Write-Host "    Please open Docker Desktop and wait for it to start, then try again." -ForegroundColor Yellow
    exit 1
}

# 2. OpenAI key set?
$envContent = Get-Content ".env" -Raw -ErrorAction SilentlyContinue
if ($envContent -match "OPENAI_API_KEY=sk-proj-your-openai-key-here" -or 
    $envContent -match "OPENAI_API_KEY=sk-proj-REPLACE" -or
    $envContent -notmatch "OPENAI_API_KEY=sk-") {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║  !! ACTION REQUIRED: Set your OpenAI API key in .env !! ║" -ForegroundColor Red
    Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "  1. Open .env in this folder"
    Write-Host "  2. Replace the placeholder on the OPENAI_API_KEY line"
    Write-Host "  3. Get a key at: https://platform.openai.com/api-keys"
    Write-Host ""
    $continue = Read-Host "Continue anyway? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") { exit 1 }
}

# ── Start services ─────────────────────────────────────────────────────────────
Write-Host ""
if ($Rebuild) {
    Write-Host "Building + starting all services (this may take a few minutes)..." -ForegroundColor Cyan
    docker compose down --remove-orphans
    docker compose build --no-cache
    docker compose up -d
} else {
    Write-Host "Starting all services..." -ForegroundColor Cyan
    docker compose up -d --build
}

Write-Host ""
Write-Host "Waiting for services to become healthy..." -ForegroundColor Cyan

# ── Wait for backend health ────────────────────────────────────────────────────
$maxWait = 120  # seconds
$elapsed = 0
$ready = $false
while ($elapsed -lt $maxWait) {
    Start-Sleep -Seconds 5
    $elapsed += 5
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        Write-Host "  [$elapsed s] Backend not ready yet, waiting..." -ForegroundColor DarkGray
    }
}

Write-Host ""
if ($ready) {
    Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║              All services are LIVE! 🚀                   ║" -ForegroundColor Green
    Write-Host "╠══════════════════════════════════════════════════════════╣" -ForegroundColor Green
    Write-Host "║  Frontend:     http://localhost:3000                     ║" -ForegroundColor Cyan
    Write-Host "║  API Docs:     http://localhost:8000/docs                ║" -ForegroundColor Cyan
    Write-Host "║  Qdrant UI:    http://localhost:6333/dashboard           ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  To view logs:  .\start.ps1 -Logs"
    Write-Host "  To stop:       .\start.ps1 -Stop"
    Write-Host "  To rebuild:    .\start.ps1 -Rebuild"
    Write-Host ""

    # Try to open the browser automatically
    Start-Process "http://localhost:3000"
} else {
    Write-Host "[!] Services may still be starting up." -ForegroundColor Yellow
    Write-Host "    Check logs with: docker compose logs -f" -ForegroundColor Yellow
    Write-Host "    Or run: .\start.ps1 -Logs" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Frontend:     http://localhost:3000" -ForegroundColor Cyan
    Write-Host "  API Docs:     http://localhost:8000/docs" -ForegroundColor Cyan
}
