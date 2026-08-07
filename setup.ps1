param(
    [switch]$SkipDockerInstall,
    [switch]$LocalDev
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   Agentic RAG Knowledge Assistant -- Setup Script" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Ensure .env exists ─────────────────────────────────────────────────────
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[+] Created .env from .env.example" -ForegroundColor Green
} else {
    Write-Host "[+] .env already exists" -ForegroundColor Green
}

# ── 2. Warn about OpenAI key ──────────────────────────────────────────────────
$envContent = Get-Content ".env" -Raw
if ($envContent -match "OPENAI_API_KEY=sk-proj-your-openai-key-here" -or
    $envContent -match "OPENAI_API_KEY=sk-proj-REPLACE") {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Yellow
    Write-Host "║  !! ACTION NEEDED: Set your OpenAI API key in .env !!   ║" -ForegroundColor Yellow
    Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Open .env and replace the OPENAI_API_KEY placeholder." -ForegroundColor White
    Write-Host "  Get a key at: https://platform.openai.com/api-keys" -ForegroundColor White
    Write-Host ""
    Write-Host "  The app will NOT be able to embed or answer questions" -ForegroundColor White
    Write-Host "  until a valid key is set." -ForegroundColor White
    Write-Host ""
}

# ── 3. Check Docker ───────────────────────────────────────────────────────────
$dockerPath = Get-Command docker -ErrorAction SilentlyContinue

if (-not $dockerPath -and -not $LocalDev) {
    if (-not $SkipDockerInstall) {
        Write-Host ""
        Write-Host "Docker Desktop not found. Installing via winget..." -ForegroundColor Yellow
        Write-Host "(This requires Windows 10/11 with WSL2 support)" -ForegroundColor DarkGray
        Write-Host ""
        winget install -e --id Docker.DockerDesktop `
            --accept-source-agreements --accept-package-agreements
        Write-Host ""
        Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
        Write-Host "║  Docker Desktop installation started!                    ║" -ForegroundColor Green
        Write-Host "╠══════════════════════════════════════════════════════════╣" -ForegroundColor Green
        Write-Host "║  NEXT STEPS:                                             ║" -ForegroundColor Yellow
        Write-Host "║  1. RESTART your computer when the installer finishes    ║" -ForegroundColor Yellow
        Write-Host "║  2. Open Docker Desktop and let it initialize (~2 min)   ║" -ForegroundColor Yellow
        Write-Host "║  3. Add your OpenAI key to .env                          ║" -ForegroundColor Yellow
        Write-Host "║  4. Run:  .\start.ps1                                    ║" -ForegroundColor Yellow
        Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
        Write-Host ""
        exit 0
    } else {
        Write-Host "Docker not found and -SkipDockerInstall set. Switching to LocalDev mode..." -ForegroundColor Yellow
        $LocalDev = $true
    }
}

# ── 4. Docker mode ────────────────────────────────────────────────────────────
if (-not $LocalDev -and $dockerPath) {
    Write-Host "[+] Docker found: $($dockerPath.Source)" -ForegroundColor Green

    # Check Docker daemon is running
    try {
        docker info *>$null 2>&1
        if ($LASTEXITCODE -ne 0) { throw "not running" }
        Write-Host "[+] Docker daemon is running" -ForegroundColor Green
    } catch {
        Write-Host ""
        Write-Host "[!] Docker is installed but not running." -ForegroundColor Red
        Write-Host "    Please open Docker Desktop, wait for it to start, then run:" -ForegroundColor Yellow
        Write-Host "    .\start.ps1" -ForegroundColor Cyan
        exit 1
    }

    Write-Host ""
    Write-Host "Running: .\start.ps1 -Rebuild" -ForegroundColor Cyan
    & "$PSScriptRoot\start.ps1" -Rebuild
    exit 0
}

# ── 5. Local Dev Setup ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Running in LOCAL DEV mode (no Docker)" -ForegroundColor Cyan
Write-Host "(PostgreSQL and Qdrant must be running locally)" -ForegroundColor DarkGray
Write-Host ""

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Write-Host "Python not found. Install Python 3.11+." -ForegroundColor Red; exit 1 }
Write-Host "[+] Python: $($python.Source) ($(python --version))" -ForegroundColor Green

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Write-Host "Node not found. Install Node.js 18+." -ForegroundColor Red; exit 1 }
Write-Host "[+] Node: $(node --version)" -ForegroundColor Green

Write-Host ""
Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
Set-Location backend
python -m pip install -r requirements.txt -q
Set-Location ..
Write-Host "[+] Backend dependencies installed" -ForegroundColor Green

Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
Set-Location frontend
npm install --legacy-peer-deps --silent
Set-Location ..
Write-Host "[+] Frontend dependencies installed" -ForegroundColor Green

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Local dev setup complete!" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  To start the backend:" -ForegroundColor White
Write-Host "    cd backend && uvicorn app.main:app --reload" -ForegroundColor Cyan
Write-Host "  To start the frontend:" -ForegroundColor White
Write-Host "    cd frontend && npm run dev" -ForegroundColor Cyan
Write-Host ""
