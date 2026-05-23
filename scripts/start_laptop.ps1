# NautiCAI — run backend + frontend on Windows laptop (dev mode).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start_laptop.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Prefer system Python if it already has torch+CUDA (skip slow .venv pip if so).
$python = "python"
try {
    $cuda = python -c "import torch; print(torch.cuda.is_available())" 2>$null
    if ($cuda -ne "True" -and (Test-Path "$Root\.venv\Scripts\python.exe")) {
        $python = "$Root\.venv\Scripts\python.exe"
    }
} catch { }
if ($python -eq "python" -and -not (Test-Path "$Root\.venv\Scripts\python.exe")) {
    Write-Host "Tip: system Python with torch+cuda is enough; optional venv:"
    Write-Host "  python -m venv .venv && .\.venv\Scripts\pip install -r backend\requirements.txt"
}

if (-not (Test-Path "$Root\backend\.env")) {
    Copy-Item "$Root\backend\.env.example" "$Root\backend\.env"
    Write-Host "Created backend\.env — edit DATABASE_URL for Supabase or leave blank for SQLite."
}

$env:NAUTICAI_DEVICE = "cuda"
$env:NAUTICAI_FP16 = "1"
# Use PyTorch/Keras weights on GPU — ONNX files fall back to CPU on Windows.
$env:NAUTICAI_BACKEND = "native"
if (-not $env:DATABASE_URL) { Remove-Item Env:NAUTICAI_USE_SQLITE -ErrorAction SilentlyContinue }

# Backend
Write-Host "Starting API on http://localhost:8000 …"
Start-Process -FilePath $python `
    -ArgumentList "-m","uvicorn","backend.main:app","--reload","--host","127.0.0.1","--port","8000" `
    -WorkingDirectory $Root -WindowStyle Normal

Start-Sleep -Seconds 3

# Frontend
if (-not (Test-Path "$Root\frontend\node_modules")) {
    Write-Host "Installing frontend deps…"
    Set-Location "$Root\frontend"
    npm install
    Set-Location $Root
}

Write-Host "Starting UI on http://localhost:5173 …"
Start-Process -FilePath "npm" -ArgumentList "run","dev" `
    -WorkingDirectory "$Root\frontend" -WindowStyle Normal

Write-Host ""
Write-Host "Open:  http://localhost:5173"
Write-Host "API:   http://localhost:8000/docs"
Write-Host "Check: Invoke-RestMethod http://localhost:8000/api/system | ConvertTo-Json"
