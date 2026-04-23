$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend  = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Python   = Join-Path $Backend "venv\Scripts\python.exe"
$BackendPort = 8000
$FrontendPort = 5174

Write-Host "================================================"
Write-Host " Calendar Assistant - Starting up"
Write-Host "================================================"
Write-Host ""

# ── Verify target ports are free ─────────────────────────────────────────────
Write-Host "[1/4] Checking ports $BackendPort and $FrontendPort..."
foreach ($portInfo in @(
    @{ Name = "Backend"; Port = $BackendPort },
    @{ Name = "Frontend"; Port = $FrontendPort }
)) {
    $conn = Get-NetTCPConnection -LocalPort $portInfo.Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Write-Host "ERROR: $($portInfo.Name) port $($portInfo.Port) is already in use by PID $($conn.OwningProcess)."
        Get-CimInstance Win32_Process -Filter "ProcessId = $($conn.OwningProcess)" |
            Select-Object ProcessId, Name, CommandLine |
            Format-List
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# ── Start backend in a new window ───────────────────────────────────────────
Write-Host "[2/4] Starting backend..."
$backendCmd = "`"$Python`" -m uvicorn backend.main:app --host 0.0.0.0 --port $BackendPort"
Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/k", "cd /d `"$Root`" && set PYTHONPATH=$Root && $backendCmd" `
    -WorkingDirectory $Root `
    -WindowStyle Normal

# ── Poll until /health responds (up to 120s) ────────────────────────────────
Write-Host "[3/4] Waiting for backend (can take 20-30s on first run)..."
$ready = $false
for ($i = 1; $i -le 120; $i++) {
    Start-Sleep 1
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$BackendPort/health" `
             -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $ready = $true
        Write-Host "  Backend ready after ${i}s!"
        break
    } catch {
        if ($i % 5 -eq 0) { Write-Host "  ...${i}s" }
    }
}

if (-not $ready) {
    Write-Host ""
    Write-Host "ERROR: Backend did not start in 120s."
    Write-Host "Check the 'Calendar Backend' window for the Python error."
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Start frontend in a new window ──────────────────────────────────────────
Write-Host "[4/4] Starting frontend..."
Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/k", "cd /d `"$Frontend`" && npm run dev -- --host 0.0.0.0 --port $FrontendPort --strictPort" `
    -WorkingDirectory $Frontend `
    -WindowStyle Normal

Start-Sleep 6
Start-Process "http://localhost:$FrontendPort"

Write-Host ""
Write-Host "================================================"
Write-Host " Backend:   http://localhost:$BackendPort"
Write-Host " Frontend:  http://localhost:$FrontendPort"
Write-Host "================================================"
Write-Host ""
Write-Host "Close the two opened terminal windows to stop."
Read-Host "Press Enter to exit this window"
