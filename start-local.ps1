param()

$ErrorActionPreference = "Stop"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  Starting Agentic RAG Assistant in Standalone Mode" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

# Ensure .env contains SQLite fallback if Postgres/Qdrant servers are not running locally
$env:DATABASE_URL = "sqlite+aiosqlite:///./ragdb.sqlite"
$env:QDRANT_HOST = ":memory:"

Write-Host "1. Starting FastAPI Backend on http://localhost:8000..." -ForegroundColor Yellow
$backendJob = Start-Job -ScriptBlock {
    Set-Location "$using:PSScriptRoot\backend"
    $env:DATABASE_URL = "sqlite+aiosqlite:///./ragdb.sqlite"
    $env:QDRANT_HOST = ":memory:"
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
}

Write-Host "2. Starting Next.js Frontend on http://localhost:3000..." -ForegroundColor Yellow
$frontendJob = Start-Job -ScriptBlock {
    Set-Location "$using:PSScriptRoot\frontend"
    $env:BACKEND_URL = "http://localhost:8000"
    npm run dev
}

Start-Sleep -Seconds 4

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Application is LIVE!" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Frontend:     http://localhost:3000" -ForegroundColor Cyan
Write-Host "  Backend API:  http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Green

Start-Process "http://localhost:3000"
